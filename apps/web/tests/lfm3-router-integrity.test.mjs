import test from "node:test";
import assert from "node:assert/strict";
import { endpointConfig, completeFleetChat, discoverFleetNodes, fleetRuntimeSnapshot } from "../lib/lfm3-fleet.mjs";
const base={name:"integrity",baseUrl:"http://127.0.0.1:19176",model:"lfm3-1.7b-test",adapter:"openai",maxInflight:1};
const body=[{role:"user",content:"synthetic fixture"}];
const catalog=()=>Response.json({data:[{id:base.model}]});
const completion=(fields={})=>Response.json({model:base.model,choices:[{message:{content:"fixture"},finish_reason:"stop"}],...fields});
test("duplicate canonical endpoint origins cannot multiply the configured capacity",()=>{
 assert.throws(()=>endpointConfig(JSON.stringify([base,{...base,name:"duplicate",baseUrl:base.baseUrl+"/"}])),/duplicate endpoint/);
});
test("explicit wrong model response is not credited as successful inference",async()=>{
 const n={...base,name:"wrong-model"};
 const fetchImpl=async url=>url.endsWith("/v1/models")?catalog():completion({model:"different-model"});
 assert.equal((await completeFleetChat(body,{nodes:[n],fetchImpl})).status,503);
 assert.equal(fleetRuntimeSnapshot(n).inFlight,0);
 assert.equal((await discoverFleetNodes([n],{fetchImpl}))[0].state,"catalog-listed");
});
test("pre-cancelled generation makes no upstream request",async()=>{
 const c=new AbortController();c.abort();let requests=0;
 const result=await completeFleetChat(body,{nodes:[{...base,name:"cancel-before"}],signal:c.signal,fetchImpl:async()=>{requests++;return catalog();}});
 assert.equal(result.status,499);assert.equal(requests,0);
});
test("cancellation during discovery prevents generation dispatch",async()=>{
 const c=new AbortController();let posts=0;
 const n={...base,name:"cancel-during"};
 const fetchImpl=async url=>{
  if(url.endsWith("/v1/models")){c.abort();return catalog();}
  posts++;return completion();
 };
 assert.equal((await completeFleetChat(body,{nodes:[n],signal:c.signal,fetchImpl})).status,499);
 assert.equal(posts,0);assert.equal(fleetRuntimeSnapshot(n).inFlight,0);
});
test("nonterminal tool-call completion is not credited as chat success",async()=>{
 const n={...base,name:"tool-call-terminal"};
 const fetchImpl=async url=>url.endsWith("/v1/models")?catalog():completion({choices:[{message:{content:"fixture",tool_calls:[{id:"fixture"}]},finish_reason:"tool_calls"}]});
 assert.equal((await completeFleetChat(body,{nodes:[n],fetchImpl})).status,503);
});
test("explicit matching model normal completion remains accepted",async()=>{
 const fetchImpl=async url=>url.endsWith("/v1/models")?catalog():completion();
 assert.equal((await completeFleetChat(body,{nodes:[{...base,name:"matching-model"}],fetchImpl})).status,200);
});

test("fallback rechecks cooldown after a concurrent failure",async()=>{
 const first={...base,name:"fallback-first",baseUrl:"http://127.0.0.1:19201"};
 const second={...base,name:"fallback-second",baseUrl:"http://127.0.0.1:19202",role:"overflow"};
 let announce,unblock;
 const entered=new Promise(r=>{announce=r});
 const pending=new Promise(r=>{unblock=r});
 let secondRequests=0;
 const fetchImpl=async url=>{
   if(url.startsWith(first.baseUrl)){announce();await pending;return new Response("",{status:503});}
   secondRequests++;return catalog();
 };
 const work=completeFleetChat(body,{nodes:[first,second],fetchImpl});
 await entered;
 try{
   const failure=await completeFleetChat(body,{nodes:[second],fetchImpl:async()=>new Response("",{status:503})});
   assert.equal(failure.status,503);
   assert.equal(fleetRuntimeSnapshot(second).cooldown,true);
 }finally{unblock();}
 assert.equal((await work).status,503);
 assert.equal(secondRequests,0);
});

test("cancelled failed catalog does not penalize endpoint",async()=>{
 const n={...base,name:"catalog-cancel-failed"};
 const c=new AbortController();
 const result=await completeFleetChat(body,{nodes:[n],signal:c.signal,fetchImpl:async()=>{c.abort();return new Response("",{status:503});}});
 assert.equal(result.status,499);
 assert.equal(fleetRuntimeSnapshot(n).cooldown,false);
 assert.equal(fleetRuntimeSnapshot(n).inFlight,0);
});

test("cancellation between fallback iterations never probes another endpoint",async()=>{
 const first={...base,name:"abort-first",baseUrl:"http://127.0.0.1:19203"};
 const second={...base,name:"abort-second",baseUrl:"http://127.0.0.1:19204",role:"overflow"};
 const c=new AbortController();let secondRequests=0;
 const result=await completeFleetChat(body,{nodes:[first,second],signal:c.signal,fetchImpl:async url=>{
   if(url.startsWith(second.baseUrl))secondRequests++;
   c.abort();return Response.json({data:[]});
 }});
 assert.equal(result.status,499);
 assert.equal(secondRequests,0);
 assert.equal(fleetRuntimeSnapshot(first).cooldown,false);
});
