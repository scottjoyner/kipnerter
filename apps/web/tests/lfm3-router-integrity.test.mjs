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
