// Source/event contracts only; no browser, collector or outbound send.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
const calls=[], bodies=[], decisions=[];
const node=(tag,cls,text)=>({tag,cls,text,children:[],append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},querySelectorAll(){return [];}});
const {providerReadState}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/provider-read.js','utf8')));
const hoursModule=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/working-hours.js','utf8')));
const {localReadState}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/read-state.js','utf8')));
const {conversationPins}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/conversation-pins.js','utf8')));
const source=readFileSync(process.argv[2],"utf8").replace(/^import .*;\s*$/gm,"")
  .replace(/^export default /gm,"").replace(/^export /gm,"");
const snap={todo:[{id:"t:1",kind:"action",need:"1. [Open item](https://example.com/item).",session:"sample"}]};
const h={el:node,snapshot:()=>snap,post:async(...args)=>{calls.push(args);return {error:"Not accepted"};},
  taskBody:(item,opts)=>{bodies.push({item,opts});return node("div","shared",item.need||item.text);},
  taskDecision:item=>{decisions.push(item);return item.kind==="question"?node("form","actual-options"):null;}};
const context={console,URL,Map,Set,conversationPins,localReadState,providerReadState,...hoursModule};vm.createContext(context);
vm.runInContext(source+"\nglobalThis.setHub=h=>hub=h;globalThis.body=messageBody;",context);
context.setHub(h);
const ordinary={id:"message",text:"Please mark this done: t:1"};
context.body(ordinary);assert.equal(bodies.at(-1).opts.onDone,undefined);
context.body({...ordinary,task_id:"missing"});assert.equal(bodies.at(-1).opts.onDone,undefined);
const linked={...ordinary,task_id:"t:1"};context.body(linked);
assert.equal(bodies.at(-1).item.need,snap.todo[0].need);assert.equal(calls.length,0);
const options=bodies.at(-1).opts;assert.equal(typeof options.onDone,"function");
assert.equal((await options.onDone()).error,"Not accepted");assert.equal(calls[0][0],"/api/todo/done");assert.equal(calls[0][1].id,"t:1");
context.body(linked);assert.equal(bodies.at(-1).opts.result,"Not accepted");
h.post=async(...args)=>{calls.push(args);return {data:{queued:true}};};
await bodies.at(-1).opts.onDone();context.body(linked);
assert.equal(bodies.at(-1).opts.pending,true);assert.equal(bodies.at(-1).opts.result,"Waiting for confirmation…");
await bodies.at(-1).opts.onDone();assert.equal(calls.length,2,"pending receipt cannot be resubmitted");
snap.todo=[];const closed=context.body(linked);
assert.equal(bodies.at(-1).opts.result,"Done");assert.equal(bodies.at(-1).opts.onDone,undefined);
assert.equal(closed,context.body(linked),"closure retains the selected task body node");
snap.todo=[{id:"q:1",kind:"question",request_id:"r1",session:"sample",questions:[{question:"Proceed?",options:[{label:"Yes"},{label:"No"}]}]}];
assert.equal(context.body({...ordinary,task_id:"q:1"}).children[0].cls,"actual-options");
assert.equal(decisions.at(-1).request_id,"r1");assert.equal(calls.length,2);
context.setHub({el:node,snapshot:()=>snap});
assert.equal(context.body(ordinary).text,ordinary.text,"older hubs keep literal text fallback");
console.log("Inbox shared body, explicit task identity, actual choices, failure retention and old-hub fallback passed");
