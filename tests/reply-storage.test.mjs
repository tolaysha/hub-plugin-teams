import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=readFileSync(process.argv[2],'utf8').replace(/^import .*;\s*$/gm,'').replace(/^export default /gm,'').replace(/^export /gm,'');
const dependencies={...await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/working-hours.js','utf8')))};
for (const [file,name] of [['provider-read','providerReadState'],['read-state','localReadState'],['conversation-pins','conversationPins']]) {
  dependencies[name]=(await import('data:text/javascript,'+encodeURIComponent(readFileSync(`web/${file}.js`,'utf8'))))[name];
}
let blocked=true;
const values=new Map(), requests=[];
const storage={getItem:k=>values.get(k)??null,removeItem:k=>values.delete(k),setItem(k,v){if(blocked)throw Error('quota');values.set(k,v);}};
const ctx=vm.createContext({console,URL,Map,Set,localStorage:storage,...dependencies});
vm.runInContext(source+'\nglobalThis.test={sendReply,savedDraft,composing,sends,setHub:h=>hub=h,error:()=>error};',ctx);
ctx.test.setHub({snapshot:()=>({sessions:[]}),postFeed:async text=>{requests.push(JSON.parse(text));return {};}});
const message={id:'synthetic',src:'telegram',contact:'synthetic-contact',reply:true,target:'synthetic-target'};
ctx.test.composing.set(message.id,{text:'Exact unsent reply'});
await ctx.test.sendReply(message,'Exact unsent reply');
assert.equal(requests.length,0);
assert.equal(ctx.test.sends.size,0);
assert.equal(ctx.test.savedDraft(message).pendingRid,null);
assert.equal(ctx.test.savedDraft(message).text,'Exact unsent reply');
assert.ok(ctx.test.composing.has(message.id));
assert.match(ctx.test.error(),/Could not save this reply before sending/);
blocked=false;
await ctx.test.sendReply(message,'Exact unsent reply');
assert.equal(requests.length,1);
assert.equal(requests[0].text,'Exact unsent reply');
assert.equal(requests[0].target,'synthetic-target');
assert.equal(ctx.test.savedDraft(message).pendingRid,requests[0].rid);
assert.equal(JSON.parse([...values.values()][0]).pendingRid,requests[0].rid);
await ctx.test.sendReply(message,'Do not duplicate');
assert.equal(requests.length,1);
console.log('Fallback reply admission refuses unsaved requests, retains text and retries once after storage recovery.');

ctx.test.setHub({snapshot:()=>({sessions:[]}),postFeed:async()=>({error:'Hub unavailable.'})});
const offline={...message,id:'offline',target:'offline-target'};
await ctx.test.sendReply(offline,'Keep uncertain reply');
assert.equal(ctx.test.error(),'');
assert.equal([...ctx.test.sends.values()].find(s=>s.id==='offline').state,'unresolved');
assert.ok(ctx.test.savedDraft(offline).pendingRid);
