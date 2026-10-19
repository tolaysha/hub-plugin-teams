import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=readFileSync(process.argv[2],'utf8').replace(/^import .*;\s*$/gm,'').replace(/^export default /gm,'').replace(/^export /gm,'');
const dependencies={...await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/working-hours.js','utf8')))};
for(const [file,name] of [['provider-read','providerReadState'],['read-state','localReadState'],['conversation-pins','conversationPins']])dependencies[name]=(await import('data:text/javascript,'+encodeURIComponent(readFileSync(`web/${file}.js`,'utf8'))))[name];
const values=new Map();
const ctx=vm.createContext({console,URL,Map,Set,localStorage:{getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)},...dependencies});
vm.runInContext(source+'\nglobalThis.test={msgs,sends,replyArchived,pendingReplyKey,restorePendingReply,acceptArchive,archiveSelection,setHub:h=>hub=h,enable:()=>archiveSupported=true};',ctx);
const t=ctx.test;t.setHub({snapshot:()=>({sessions:[]})});t.enable();
const m={id:'primary',src:'dm',contact:'synthetic-contact',target:'primary-target'};
const older={...m,id:'older',target:'older-target'};
t.msgs.set(m.id,m);t.msgs.set(older.id,older);
const q={kind:'send',id:m.id,rid:'original',text:'Guarded original',target:m.target,inbox:{version:'original-version'},archive:true,archive_ids:[m,older].map(({id,target,contact})=>({id,target,contact}))};
values.set(t.pendingReplyKey(m),JSON.stringify({q,ts:1}));
t.restorePendingReply(m); // Snapshot lacks config/token; the admitted payload still proves guarding.
const receipt={kind:'archived',id:m.id,rid:q.rid,target:m.target,ids:[m.id,older.id],members:q.archive_ids};
t.acceptArchive(receipt);
assert.equal(t.replyArchived.size,0,'Reload must not weaken a guarded original request');
t.acceptArchive({...receipt,version:'wrong',receipt:{id:'provider-receipt'}});
assert.equal(t.replyArchived.size,0);
// A second reply starts on an older member while the first archive awaits delivery.
t.sends.set('other-reply',{kind:'send',id:older.id,rid:'other-reply',target:older.target,state:'unresolved'});
assert.deepEqual(Array.from(t.archiveSelection(m),x=>x.id),[m.id],'Do not include another pending delivery');
t.acceptArchive({...receipt,version:q.inbox.version,receipt:{id:'provider-receipt'}});
assert.equal(t.replyArchived.has(m.id),true);
assert.equal(t.replyArchived.has(older.id),false,'A late receipt must not hide an independently pending reply');
t.msgs.set(m.id,{...m,target:'x'.repeat(301)});
assert.throws(()=>t.archiveSelection(t.msgs.get(m.id)),/cannot be archived safely/);
console.log('Guarded archive reload and concurrent sibling delivery retain their original boundaries.');
