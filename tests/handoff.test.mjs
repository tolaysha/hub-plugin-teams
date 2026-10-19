import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
const source=readFileSync(process.argv[2],'utf8').replace(/^import .*;\s*$/gm,'').replace(/^export default /gm,'').replace(/^export /gm,'');
class Element{constructor(tag,cls,text){Object.assign(this,{tag,cls,textContent:text,children:[],listeners:{}});}append(...c){this.children.push(...c);}setAttribute(k,v){this[k]=v;}addEventListener(k,v){this.listeners[k]=v;}}
// I-54 (перенесено из task/inbox-post-actions): main.js теперь зовёт модули плагина на верхнем уровне — даём их
const dependencies={T:(ru,en)=>en,...await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/working-hours.js','utf8')))};
for (const [file,name] of [['provider-read','providerReadState'],['read-state','localReadState'],['conversation-pins','conversationPins']]) {
  dependencies[name]=(await import('data:text/javascript,'+encodeURIComponent(readFileSync(`web/${file}.js`,'utf8'))))[name];
}
const storage=new Map();
const c={console,URL,Map,Set,Date,location:{hash:''},...dependencies,localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>{storage.set(key,value);},removeItem:key=>storage.delete(key)}};vm.createContext(c);
vm.runInContext(source+'\nglobalThis.t={toHub,sendLatest,agentMenu,humanSummary,latestTarget,reviewAgents,handoffs,composing,editorDrafts,done,setHub:h=>hub=h,getError:()=>error};',c);
const m={id:'source',post:'p42',from:'Irrigar Pinamar',src:'whatsapp',text:'Try the nursery across the street.',at:'2026-10-15T12:00:00Z'};
let sessions=[{name:'canonical',kind:'hub'},{name:'noe',role:'agent',state:'asleep'},{name:'visited',state:'idle'}];
const prepared=[],posts=[];
// Exercise the real paired adapter: hub.post is api.post, which wraps successful
// JSON in {data} and converts fetch failures into {error}, rather than throwing.
const core=process.argv[3] || process.env.HUB_CORE || resolve('../agents-hub-core');
const api=readFileSync(`${core}/modules/web/static/js/api.js`,'utf8');
const ext=readFileSync(`${core}/modules/web/static/js/ext.js`,'utf8');
assert.match(ext,/import \{ post \} from "\.\/api\.js"/);assert.match(ext,/^  post,$/m);
let response=()=>({ok:true,json:async()=>({ok:true})});
const transport={fetch:async(path,options)=>{posts.push({path,body:JSON.parse(options.body)});return response();}};
vm.createContext(transport);
const postSource=api.match(/export async function post\(path, body\) \{[\s\S]*?\n\}/)?.[0];
assert.ok(postSource,'Actual core POST adapter must be available');
vm.runInContext(postSource.replace('export ', '')+'\nglobalThis.post=post;',transport);
const hub={snapshot:()=>({sessions}),el:(...a)=>new Element(...a),icon:()=>new Element('svg'),capabilities:{inboxHandoff:1},handoff:{latest:()=>({name:'visited',title:'Last opened conversation'})},
  compose:(...args)=>{prepared.push(args);return true;},post:transport.post};
c.t.setHub(hub);
const menu=c.t.agentMenu(m);assert.deepEqual(menu.children.map(x=>x.value),['canonical','noe']);
menu.children.find(x=>x.value==='noe').listeners.click();assert.equal(prepared.length,0,'Choosing agent does not send or navigate');
assert.deepEqual(JSON.parse(storage.get('hub.inbox.reviewAgents')),[[JSON.stringify(['whatsapp','whatsapp:source']),'noe']],'Conversation choice is persisted locally');
const restarted={console,URL,Map,Set,Date,...dependencies,localStorage:c.localStorage};vm.createContext(restarted);
vm.runInContext(source+'\nglobalThis.choice=reviewAgents.get(JSON.stringify(["whatsapp","whatsapp:source"]));',restarted);assert.equal(restarted.choice,'noe');
await c.t.toHub(m,'work');assert.equal(prepared[0][0],'noe');assert.equal(posts.length,0,'Manual Work stays editable before send');
assert.ok(prepared[0][2].quote.includes('p42'));assert.equal(prepared[0][2].quotePreview,'Irrigar Pinamar: Try the nursery across the street.');
assert.equal(c.t.reviewAgents.has(JSON.stringify(['whatsapp','whatsapp:other'])),false,'Selection is scoped to this conversation, not global triage');
const reposted={...m,post:'p90'};
assert.equal(c.t.agentMenu(reposted).value,'noe','Choice survives a re-post of the conversation under a new post id');
await c.t.toHub(reposted,'work');assert.equal(prepared[1][0],'noe','Work goes to the chosen agent after a re-post');
assert.ok(prepared[1][2].quote.includes('p90'),'The quote still names the exact current post');
assert.equal(c.t.agentMenu({...m,id:'other',post:'p91'}).value,'canonical','Another conversation keeps the default');
assert.equal(c.t.agentMenu({...m,id:'other',post:'p91',contact:'someone'}).value,'canonical');
c.t.reviewAgents.set('p77','noe');assert.equal(c.t.agentMenu({...m,id:'legacy',post:'p77'}).value,'noe','Earlier post-keyed choice still applies to that exact post');
c.t.reviewAgents.delete('p77');
prepared.length=1;
sessions=sessions.filter(s=>s.name!=='noe');await c.t.toHub(m,'work');assert.equal(prepared.length,1,'Removed agent never silently reroutes to Hub');assert.match(c.t.getError(),/unavailable/);
c.t.composing.set(m.id,{text:'Saved private reply'});c.t.editorDrafts.set(m.id,'Saved draft');
await c.t.sendLatest(m);assert.equal(posts.length,1);assert.equal(posts[0].path,'/api/send');assert.equal(posts[0].body.session,'visited');assert.ok(posts[0].body.quote.includes('p42'));assert.ok(posts[0].body.client_id.length>=8);
assert.equal(c.t.handoffs.get(JSON.stringify(['canonical','p42','visited'])).state,'queued','Real adapter acceptance is read from data.ok');
assert.equal(c.t.done(m),false,'Internal handoff does not falsely resolve the external Inbox message');
assert.equal(c.t.composing.get(m.id).text,'Saved private reply');assert.equal(c.t.editorDrafts.get(m.id),'Saved draft');
await c.t.sendLatest(m);assert.equal(posts.length,1,'Accepted intent is not automatically duplicated');
const missing={...m,post:'p43'};sessions=sessions.filter(s=>s.name!=='visited');await c.t.sendLatest(missing);assert.equal(posts.length,1,'Removed latest target blocks delivery');
c.t.setHub({...hub,capabilities:{}});assert.equal(c.t.latestTarget(),null,'Old core exposes no invented latest thread');
sessions.push({name:'visited',state:'idle'});
// Plugin API below 1.16: no hub.compose. Work degrades to the earlier direct send, through the real adapter, with no error on screen.
{
  const noCompose={...hub};delete noCompose.compose;
  const feedPosts=[];noCompose.postFeed=async b=>{feedPosts.push(JSON.parse(b));return {data:{ok:true}};};
  c.t.setHub(noCompose);c.t.reviewAgents.set(JSON.stringify(['whatsapp','whatsapp:legacy']),'visited');
  const legacy={...m,id:'legacy',post:'p60'};const n=posts.length;
  await c.t.toHub(legacy,'work');
  assert.equal(c.t.getError(),'','No capability error without hub.compose');
  assert.equal(posts.length,n+1);assert.equal(posts.at(-1).path,'/api/send');assert.equal(posts.at(-1).body.session,'visited','Direct send goes to the chosen agent');
  assert.ok(posts.at(-1).body.text.includes('p60'));assert.equal(feedPosts.at(-1).kind,'work');
  assert.equal(c.t.done(legacy),true);
  c.t.setHub({...hub,postFeed:async()=>({}),compose:undefined});
  response=()=>{throw Error('lost');};const lost={...m,id:'legacy2',post:'p61'};
  await c.t.toHub(lost,'work');assert.match(c.t.getError(),/./,'A transport error from the real adapter is surfaced, not swallowed');
  response=()=>({ok:true,json:async()=>({ok:true})});
}
c.t.setHub(hub);
async function unresolved(post,reply){
  response=reply;const item={...m,post};const before=posts.length;
  await c.t.sendLatest(item);
  assert.equal(c.t.handoffs.get(JSON.stringify(['canonical',post,'visited'])).state,'unresolved',post);
  assert.match(c.t.handoffs.get(JSON.stringify(['canonical',post,'visited'])).message,/status unknown/);
  await c.t.sendLatest(item);assert.equal(posts.length,before+1,'Uncertain result never enables another POST');
}
await unresolved('p43',()=>{throw Error('Server accepted but response was lost');});
await unresolved('p44',()=>({ok:true,json:async()=>{throw Error('Truncated response');}}));
await unresolved('p45',()=>({ok:false,json:async()=>({error:'Request failed'})}));
await unresolved('p46',()=>({ok:true,json:async()=>({ok:false,error:'Not accepted'})}));
await unresolved('p47',()=>({ok:true,json:async()=>({ok:true,error:'Conflicting result'})}));
response=()=>({ok:true,json:async()=>({ok:true})});
const concurrent={...m,post:'p48'},before=posts.length;
await Promise.all([c.t.sendLatest(concurrent),c.t.sendLatest(concurrent)]);
assert.equal(posts.length,before+1,'Pending taps share one intent');
assert.equal(c.t.handoffs.get(JSON.stringify(['canonical','p48','visited'])).state,'queued');
function reload(localStorage=c.localStorage){
  const restarted={console,URL,Map,Set,Date,...dependencies,localStorage};vm.createContext(restarted);
  vm.runInContext(source+'\nglobalThis.t={sendLatest,handoffs,setHub:h=>hub=h,getError:()=>error};',restarted);
  restarted.t.setHub(hub);return restarted;
}
const afterReload=reload(),beforeReloadPosts=posts.length;
await afterReload.t.sendLatest(m);await afterReload.t.sendLatest({...m,post:'p43'});
assert.equal(posts.length,beforeReloadPosts,'Queued and unresolved intents survive reload without allocating another send');
assert.equal(afterReload.t.handoffs.get(JSON.stringify(['canonical','p42','visited'])).client_id,posts[0].body.client_id,'Reload retains exact accepted operation identity');
let finish;
response=()=>new Promise(resolve=>{finish=resolve;});
const interrupted={...m,post:'p49'},inFlight=c.t.sendLatest(interrupted);
await reload().t.sendLatest(interrupted);
assert.equal(posts.length,beforeReloadPosts+1,'Intent persists before the request can lose its response');
finish({ok:true,json:async()=>({ok:true})});await inFlight;
const broken=reload({getItem(){throw Error('Storage denied');},setItem(){throw Error('Storage denied');}});
await broken.t.sendLatest({...m,post:'p50'});
assert.equal(posts.length,beforeReloadPosts+1,'No request if durable intent cannot be read');
const full=reload({getItem:()=>null,setItem(){throw Error('Quota exceeded');}});
await full.t.sendLatest({...m,post:'p51'});
assert.equal(posts.length,beforeReloadPosts+1,'No request if durable intent cannot be written');
const corrupted=reload({getItem:()=>'{broken',setItem(){}});
await corrupted.t.sendLatest({...m,post:'p52'});
assert.equal(posts.length,beforeReloadPosts+1,'Unreadable history never silently becomes an empty ledger');
const silent=reload({getItem:()=>null,setItem(){}});
await silent.t.sendLatest({...m,post:'p53'});
assert.equal(posts.length,beforeReloadPosts+1,'Write acknowledgment requires reading back the saved identity');
response=()=>({ok:true,json:async()=>({ok:true})});
sessions[0]={name:'other-hub',kind:'hub'};
await reload().t.sendLatest(m);
assert.equal(posts.length,beforeReloadPosts+2,'Different canonical Hub has a separate source/target intent');
sessions[0]={name:'canonical',kind:'hub'};
await reload().t.sendLatest(m);
assert.equal(posts.length,beforeReloadPosts+2,'Returning to original Hub restores its existing intent');
// Ledger: a full ledger evicts its oldest settled intents instead of blocking, and renders do not re-parse it.
{
  const ledger=new Map(),store={getItem:k=>{reads++;return ledger.get(k)??null;},setItem:(k,v)=>{ledger.set(k,v);}};let reads=0;
  const row=(i,state)=>{const x={hub:'canonical',post:'old'+i,target:'visited',client_id:'client-'+String(i).padStart(4,'0'),state};return [JSON.stringify([x.hub,x.post,x.target]),x];};
  const rows=Array.from({length:500},(_,i)=>row(i,i===0?'wait':'queued'));
  ledger.set('hub.inbox.handoffs.v1',JSON.stringify(rows));
  const w={console,URL,Map,Set,Date,...dependencies,localStorage:store};vm.createContext(w);
  let parses=0;const J=JSON;w.JSON={parse:(...a)=>{parses++;return J.parse(...a);},stringify:J.stringify};
  vm.runInContext(source+'\nglobalThis.t={sendLatest,restoreHandoffs,handoffs,setHub:h=>hub=h};',w);w.t.setHub(hub);
  const base=posts.length;await w.t.sendLatest({...m,post:'fresh'});
  assert.equal(posts.length,base+1,'A full ledger does not block a new handoff');
  const kept=J.parse(ledger.get('hub.inbox.handoffs.v1')).map(r=>r[1].post);
  assert.equal(kept.length,500);assert.ok(kept.includes('fresh'));assert.equal(kept.includes('old0'),false,'Oldest intent is evicted first');
  assert.ok(kept.includes('old1'),'Only as many as needed are evicted');
  parses=0;for(let i=0;i<20;i++)w.t.restoreHandoffs();
  assert.equal(parses,0,'Unchanged ledger is not parsed again per render');
  const other=J.parse(ledger.get('hub.inbox.handoffs.v1'));other.pop();ledger.set('hub.inbox.handoffs.v1',J.stringify(other));
  w.t.restoreHandoffs();assert.equal(parses,1,'Storage changed elsewhere is re-read');assert.equal(w.t.handoffs.size,499);
}
console.log('Inbox agent choice, human preview, explicit latest-thread queue and old-core boundaries pass');
