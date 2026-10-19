// Event replay and in-memory editor only. No browser, accounts or outbound sends.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const {providerReadState}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/provider-read.js','utf8')));
const hoursModule=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/working-hours.js','utf8')));
const {localReadState}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/read-state.js','utf8')));
const {conversationPins}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/conversation-pins.js','utf8')));
const source=readFileSync(process.argv[2], 'utf8').replace(/^import .*;\s*$/gm,'')
  .replace(/^export default /gm,'').replace(/^export /gm,'');
const key='wa:sample:123@c.us:abc', contact='wa:sample:123@c.us';
const post=(n,data,by='плагин teams',reply_to=null)=>({id:`p${n}`,by,text:typeof data==='string'?data:JSON.stringify(data),reply_to});
const initial=[post(9,{kind:'config',signature:'Existing configured signature'}),
  post(10,{kind:'msg',id:key,contact,reply:true}),post(20,{kind:'answered',id:key}),
  post(21,'inert owner post','owner','p10'),post(22,'The exact unsent draft','helper','p10')];
const correction=post(23,{kind:'reopened',id:key,post:'p10',corrects:'p20',contact,reset_history:true});
async function replay(batches, ownText) {
  const ctx={console,URL,Map,Set,conversationPins,localReadState,providerReadState,...hoursModule,T:(ru,en)=>ru};vm.createContext(ctx);
  vm.runInContext(source+`\nglobalThis.test={sync,setHub:h=>hub=h,done,canReply,msgs,replies,composing};`,ctx);
  let at=0,sends=0;
  ctx.test.setHub({feed:async()=>batches[at++]||[],post:async()=>{sends++;throw Error('must not send');}});
  for(let i=0;i<batches.length;i++) {
    if(i===1&&ownText)ctx.test.composing.set(key,{text:ownText});
    await ctx.test.sync();
  }
  return {...ctx.test,sends};
}
const fixed=await replay([initial,[correction]]);
assert.equal(fixed.canReply(fixed.msgs.get(key)),true);
assert.equal(fixed.done(fixed.msgs.get(key)),false);
assert.equal(fixed.msgs.get(key).post,'p10');
assert.equal(fixed.replies.get('p10').length,1);
assert.equal(fixed.composing.get(key)?.text,'The exact unsent draft');
assert.equal(fixed.sends,0);
const reloaded=await replay([[...initial,correction,correction]]);
assert.equal(reloaded.canReply(reloaded.msgs.get(key)),true);
assert.equal(reloaded.replies.get('p10').length,1);
const edited=await replay([initial,[correction]],'Owner edit');
assert.equal(edited.composing.get(key).text,'Owner edit');
for(const bad of [post(23,JSON.parse(correction.text),'helper'),
  post(23,{...JSON.parse(correction.text),contact:'other'}),
  post(23,{...JSON.parse(correction.text),post:'p9'})]) {
  const test=await replay([initial,[bad]]);assert.equal(test.canReply(test.msgs.get(key)),false);
}
for(const kind of ['answered','sent']) {
  const test=await replay([initial,[post(23,{kind,id:key,rid:'r1'}),post(24,JSON.parse(correction.text))]]);
  assert.equal(test.canReply(test.msgs.get(key)),false);
}
// Receipt replay cannot turn successful delivery into an unsent correction.
const confirmed=await replay([initial,[post(23,{kind:'sent',id:key,rid:'r1'}),post(24,{kind:'sent',id:key,rid:'r1'}),
  post(25,{kind:'reopened',id:key,post:'p10',corrects:'p23',contact})]]);
assert.equal(confirmed.canReply(confirmed.msgs.get(key)),false);
assert.equal(confirmed.done(confirmed.msgs.get(key)),true);
console.log('Exact closure correction, restart, draft preservation, editor and send boundary passed');
if(process.argv[3]) {
  const fixture=JSON.parse(readFileSync(process.argv[3],'utf8'));
  const ctx={console,URL,Map,Set,conversationPins,localReadState,providerReadState,...hoursModule,T:(ru,en)=>ru};vm.createContext(ctx);
  vm.runInContext(source+`\nglobalThis.test={sync,setHub:h=>hub=h,done,canReply,msgs,replies,composing};`,ctx);
  let batch=fixture.posts;
  ctx.test.setHub({feed:async()=>{const p=batch;batch=[];return p;},post:async()=>{throw Error('outbound prohibited');}});
  await ctx.test.sync();
  const target=fixture.correction.id;
  assert.equal(ctx.test.canReply(ctx.test.msgs.get(target)),false);
  batch=[{id:'p999999999',by:'плагин teams',text:JSON.stringify(fixture.correction)}];
  await ctx.test.sync();
  assert.equal(ctx.test.canReply(ctx.test.msgs.get(target)),true);
  assert.equal(ctx.test.done(ctx.test.msgs.get(target)),false);
  assert.equal(ctx.test.msgs.get(target).post,fixture.correction.post);
  assert.equal(ctx.test.composing.get(target).text,fixture.draft);
  assert.equal(ctx.test.replies.get(fixture.correction.post).at(-1).text,fixture.draft);
  console.log('Captured incident projection: original source and exact recovered draft restored to unsent editor');
}
