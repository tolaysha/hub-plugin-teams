import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=readFileSync(process.argv[2],'utf8').replace(/^import .*;\s*$/gm,'').replace(/^export default /gm,'').replace(/^export /gm,'');
const {providerReadState}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/provider-read.js','utf8')));
const hoursModule=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/working-hours.js','utf8')));
const {localReadState}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/read-state.js','utf8')));
const {conversationPins}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/conversation-pins.js','utf8')));
const ctx={console,URL,Map,Set,conversationPins,localReadState,providerReadState,...hoursModule,T:(ru,en)=>ru};vm.createContext(ctx);
vm.runInContext(source+'\nglobalThis.t={sync,replies,setHub:h=>hub=h};',ctx);
const posts=[{id:'p1',by:'helper',reply_to:'p42',text:JSON.stringify({kind:'revision_result',text:'Public reply',context:'Private instruction',next_action:'Private action'})},
  {id:'p2',by:'helper',reply_to:'p42',text:JSON.stringify({kind:'draft_proposal',text:'Unverified proposed reply',requires_apply:true})}];
ctx.t.setHub({feed:async()=>posts});await ctx.t.sync();
assert.equal(ctx.t.replies.size,0,'Raw session JSON must not become an actionable public reply');
console.log('Structured private results cannot bypass the collector-authored explicit proposal path');
