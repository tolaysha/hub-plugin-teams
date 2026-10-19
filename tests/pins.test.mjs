import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {conversationPins}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/conversation-pins.js','utf8')));
const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
let scope='hub-a';let pins=conversationPins(()=>scope,storage);
const a=JSON.stringify(['telegram','account-a/chat']),b=JSON.stringify(['email','account-a/chat']);
assert.equal(pins.toggle(a),true);assert.equal(pins.has(a),true);assert.equal(pins.has(b),false);
scope='hub-b';assert.equal(pins.has(a),false);pins.toggle(b);
scope='hub-a';assert.equal(pins.has(a),true);assert.equal(pins.has(b),false);
pins=conversationPins(()=>scope,storage);assert.equal(pins.has(a),true);pins.toggle(a);assert.equal(pins.has(a),false);
const denied=conversationPins(()=>scope,{getItem:storage.getItem,setItem(){throw Error('quota')}});
assert.equal(denied.toggle(a),false);assert.equal(denied.has(a),false);
Object.defineProperty(globalThis,'localStorage',{get(){throw Error('denied')},configurable:true});
const blocked=conversationPins(()=>scope);assert.equal(blocked.has(a),false);assert.equal(blocked.toggle(a),false);
console.log('Conversation pins preserve Hub/source identity, reload state and honest storage failure');

const tabA=conversationPins(()=> 'shared-hub',storage),tabB=conversationPins(()=> 'shared-hub',storage);
tabA.has(a);tabB.has(b);tabA.toggle(a);tabB.toggle(b);
assert.equal(tabA.has(b),true,'a second tab pin must appear without a reload');
assert.equal(tabB.has(a),true,'pinning in a second tab must not erase the first pin');

let invalidWrites=0;
const corrupt={getItem:()=>'{broken',setItem(){invalidWrites++;}};
assert.equal(conversationPins(()=> 'hub',corrupt).toggle(a),false);
const transient={getItem(){throw Error('unreadable')},setItem(){invalidWrites++;}};
assert.equal(conversationPins(()=> 'hub',transient).toggle(a),false);

values.set('hub.inbox.pinned.v1:legacy',JSON.stringify([JSON.stringify(['channel','thread'])]));
assert.equal(conversationPins(()=> 'legacy',storage).has(JSON.stringify(['teams','thread'])),true,'already saved Teams pins migrate without loss');

assert.equal(invalidWrites,0,'unreadable preferences must never be overwritten');
