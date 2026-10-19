import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../web/editor-state.js',import.meta.url),'utf8');
const {InboxEditor}=await import('data:text/javascript,'+encodeURIComponent(source));
const token={v:1,version:'source-A',edit_version:0,held:false,holder:null};
const message={id:'source',post:'p42',inbox:token};
const start=()=>new InboxEditor(message,'web-tab','Owner exact draft');
const confirm=(e,rid='hold')=>{
  e.hold(rid);
  const held={...token,edit_version:1,held:true,holder:'web-tab'};
  assert.equal(e.receive({kind:'draft_state',id:'source',rid,inbox:held}),true);return held;
};
for (const kind of ['thread','media','msg','status']) {
  const idle=start();
  assert.equal(idle.receive({kind,id:'source'}),false);
  assert.equal(idle.text,'Owner exact draft');
}
const e=start();assert.throws(()=>e.send('send','Hello'),/Confirm/);
const hold=e.hold('hold');assert.equal(hold.editor,'web-tab');
assert.equal(e.receive({kind:'draft_state',id:'other',rid:'hold',inbox:{...token,edit_version:1}}),false);
assert.throws(()=>e.send('send','Hello'),/Wait/);
e.receive({kind:'draft_control_failed',id:'source',rid:'hold',error:'Other client is editing'});
assert.equal(e.text,'Owner exact draft');assert.throws(()=>e.send('send','Hello'),/Other client/);
const revised=start();const held=confirm(revised);revised.edit('');revised.direct('Suggest 11 instead.');
const q=revised.revise('ask');assert.equal(q.draft,'');assert.equal(q.post,'p42');
const current={...held,edit_version:2};revised.receive({kind:'draft_state',id:'source',rid:'ask',inbox:current});
const proposal={kind:'draft_proposal',id:'source',post:'p42',rid:'ask',editor:'web-tab',inbox:current,
  text:'Could we meet at 11?',context:'The time changed.',next_action:'Review the reply.',requires_apply:true};
assert.equal(revised.receive({...proposal,post:'p41'}),false);
assert.equal(revised.receive({...proposal,editor:'other-client'}),false);
assert.equal(revised.receive(proposal),true);assert.equal(revised.text,'');
revised.edit('My newer edit');assert.throws(()=>revised.apply(),/changed/);assert.equal(revised.text,'My newer edit');
const accepted=start();confirm(accepted);accepted.direct('Suggest 11.');accepted.revise('ask');
accepted.receive({kind:'draft_state',id:'source',rid:'ask',inbox:current});accepted.receive(proposal);
assert.equal(accepted.apply().text,'Could we meet at 11?');
const send=accepted.send('send','Only the approved reply');assert.equal(send.text,'Only the approved reply');
assert.equal('instruction' in send,false);assert.throws(()=>accepted.send('send2','Again'),/Wait/);
assert.equal(accepted.receive({kind:'sent',id:'source',rid:'send',submitted_inbox:current,inbox:current}),false);
assert.equal(accepted.receive({kind:'send_uncertain',id:'source',rid:'send',error:'Unresolved'}),true);
assert.throws(()=>accepted.send('send2','Again'),/Unresolved/);
assert.equal(accepted.text,'Could we meet at 11?');
const uncertain=start();confirm(uncertain);uncertain.send('unknown','Exact reply');
assert.equal(uncertain.receive({kind:'send_failed',id:'source',rid:'unknown',unresolved:true,error:'Unknown delivery'}),true);
assert.equal(uncertain.delivery?.state,'unresolved');
assert.throws(()=>uncertain.send('new-request','Exact reply'),/Unknown delivery/);
const done=start();const version=confirm(done);done.send('send','Owner reply');
assert.equal(done.receive({kind:'sent',id:'source',rid:'send',submitted_inbox:{...version,version:'other'},receipt:{id:'id'}}),false);
assert.equal(done.receive({kind:'sent',id:'source',rid:'send',submitted_inbox:version,inbox:{...version,held:false},receipt:{id:'real-id'}}),true);
assert.equal(done.delivery.state,'sent');
done.edit('A newer owner draft');
for (const kind of ['send_failed','send_blocked','send_uncertain','scheduled','canceled','send_duplicate']) {
  assert.equal(done.receive({kind,id:'source',rid:'send',state:'pending',error:'Late obsolete delivery update'}),false);
  assert.equal(done.delivery?.state,'sent');
  assert.equal(done.error,'');
  assert.equal(done.text,'A newer owner draft');
}
for (const kind of ['sent','send_duplicate']) {
  assert.equal(done.receive({kind,id:'source',rid:'send',submitted_inbox:version,inbox:version,version:version.version,state:'sent',receipt:{id:'real-id'}}),false);
  assert.equal(done.text,'A newer owner draft');
}
const changed=start();confirm(changed);changed.observe({...message,inbox:{...token,version:'new-facts'}});
assert.throws(()=>changed.send('send','Old reply'),/conversation changed/);
const scheduled=start();confirm(scheduled);
assert.equal(scheduled.send('scheduled','Exact future reply',{at:'2099-06-17T15:30:00.000Z'}).at,'2099-06-17T15:30:00.000Z');
const bound=start();const boundVersion=confirm(bound);
assert.equal(bound.send('bound','Exact recipient',{target:'recipient-a'}).target,'recipient-a');
for(const target of [undefined,'recipient-b']) {
  assert.equal(bound.receive({kind:'send_failed',id:'source',rid:'bound',target,error:'Wrong target'}),false);
  assert.equal(bound.receive({kind:'sent',id:'source',rid:'bound',target,submitted_inbox:boundVersion,inbox:boundVersion,receipt:{id:'wrong'}}),false);
}
assert.equal(bound.delivery.state,'queued');
assert.equal(bound.receive({kind:'sent',id:'source',rid:'bound',target:'recipient-a',submitted_inbox:boundVersion,inbox:boundVersion,receipt:{id:'right'}}),true);
for (const kind of ['sent','send_duplicate']) {
  const recovered=start(),v=confirm(recovered);recovered.send('recover','Exact reply');
  recovered.receive({kind:'send_uncertain',id:'source',rid:'recover'});
  assert.match(recovered.error,/awaiting confirmation/);
  assert.equal(recovered.receive({kind,id:'source',rid:'recover',submitted_inbox:v,inbox:v,version:v.version,state:'sent',receipt:{id:'confirmed'}}),true);
  assert.equal(recovered.error,'');
}
for (const kind of ['send_failed','send_blocked']) {
  const retry=start(),first=confirm(retry);retry.send('first','Original reply',{target:'recipient-a'});
  assert.equal(retry.receive({kind,id:'source',rid:'first',target:'recipient-a',error:'Definitive refusal'}),true);
  retry.edit('Newer owner edit');assert.throws(()=>retry.send('retry','Newer owner edit'),/refusal/);
  retry.hold('reconfirm');assert.equal(retry.error,'');
  assert.throws(()=>retry.send('retry','Newer owner edit'),/Wait/);
  assert.equal(retry.receive({kind:'draft_state',id:'source',rid:'reconfirm',inbox:first}),false);
  assert.throws(()=>retry.send('retry','Newer owner edit'),/confirmation/);
  const next={...first,edit_version:2};
  assert.equal(retry.receive({kind:'draft_state',id:'source',rid:'reconfirm',inbox:next}),true);
  assert.equal(retry.send('retry',retry.text,{target:'recipient-a'}).text,'Newer owner edit');
  assert.equal(retry.receive({kind,id:'source',rid:'first',target:'recipient-a'}),false);
  assert.equal(retry.delivery.rid,'retry');
}
console.log('Inbox editor: identity, CAS, stale proposals, explicit Apply and truthful delivery passed');
const refusedChanged=start();confirm(refusedChanged);refusedChanged.send('refused','Original');
refusedChanged.receive({kind:'send_blocked',id:'source',rid:'refused',error:'Definitive refusal'});
refusedChanged.observe({...message,inbox:{...token,version:'replacement'}});
assert.throws(()=>refusedChanged.hold('fresh',{...token,version:'replacement'}),/conversation changed/);
const monotonic=start();confirm(monotonic);monotonic.token={...monotonic.token,edit_version:5};
assert.throws(()=>monotonic.hold('old',{...monotonic.token,edit_version:1}),/changed|current/);
