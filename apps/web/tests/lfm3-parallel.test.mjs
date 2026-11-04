import test from "node:test";
import assert from "node:assert/strict";
import { runParallelLFM3Research } from "../lib/lfm3-parallel.mjs";
import { completeFleetChat } from "../lib/lfm3-fleet.mjs";

const model = "lfm3-1.7b-research";
const nodes = [
  { name: "parallel-alpha", baseUrl: "http://100.83.215.83:19175", model, adapter: "openai", maxInflight: 1 },
  { name: "parallel-beta", baseUrl: "http://100.78.106.121:19175", model, adapter: "openai", maxInflight: 1 },
];
const args = { question: "Compare capacity options", subtasks: ["Analyze throughput", "Analyze memory"], nodes };
function transport() {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/v1/models")) return Response.json({data:[{id:model}]});
    return Response.json({choices:[{message:{content:"One bounded summary."}}]});
  };
  return {calls,fetchImpl};
}
test("anonymous requests cannot fan out to multiple fleet workers", async () => {
  const api = transport();
  const result = await runParallelLFM3Research({ ...args, fetchImpl:api.fetchImpl });
  assert.equal(result.status,403);
  assert.equal(api.calls.length,0);
});
test("bounded model-only parallel work distributes two workers across ready nodes", async () => {
  const api = transport();
  const result = await runParallelLFM3Research({ ...args, authorized:true, fetchImpl:api.fetchImpl });
  assert.equal(result.status,200);
  assert.equal(new Set(result.workerRuntimes).size,2);
  assert.equal(api.calls.filter(x => x.url.endsWith("/v1/chat/completions")).length,3);
  for(const call of api.calls.filter(x => x.url.endsWith("/completions"))) {
    const request=JSON.parse(call.options.body);
    assert.equal(request.model,model);
    assert.equal(request.tools,undefined);
    assert.match(request.messages.at(-1).content, /Compare capacity options/);
  }
});
test("fanout rejects excessive tasks and one-node oversubscription", async () => {
  const api=transport();
  const a=await runParallelLFM3Research({...args,authorized:true,subtasks:Array.from({length:5},(_,i)=>String(i)),fetchImpl:api.fetchImpl});
  assert.equal(a.status,400);
  const b=await runParallelLFM3Research({...args,authorized:true,nodes:[nodes[0]],fetchImpl:api.fetchImpl});
  assert.equal(b.status,400);
  assert.equal(api.calls.length,0);
});
test("incomplete worker results never become an asserted completed answer", async () => {
  const api=transport();
  let count=0;
  const fetchImpl=async (url, opts) => {
    if(url.endsWith("/v1/models"))return Response.json({data:[{id:model}]});
    count++;
    if(count===1)return Response.json({choices:[{message:{content:""}}]});
    return Response.json({choices:[{message:{content:"valid"}}]});
  };
  const result=await runParallelLFM3Research({...args,authorized:true,fetchImpl});
  assert.equal(result.status,503);
});

test("oversized research question is rejected rather than truncated or overfilling synthesis", async () => {
  const result=await runParallelLFM3Research({...args,authorized:true,question:"x".repeat(701)});
  assert.equal(result.status,400);
});

test("three research perspectives require three distinct configured workers before any inference", async () => {
  const { calls, fetchImpl } = transport();
  const result = await runParallelLFM3Research({
    ...args, authorized:true, subtasks:["Analyze accuracy","Analyze latency","Analyze memory"],
    nodes:[...nodes], fetchImpl,
  });
  assert.equal(result.status,400);
  assert.equal(calls.length,0, "insufficient workers must not burn tokens");
});
test("two successful fallbacks to one physical node cannot masquerade as independent workers", async () => {
  const model="lfm3-1.7b-research";
  const primary={name:"unique-alpha",baseUrl:"http://100.83.215.83:19175",
    model, adapter:"openai", maxInflight:2, role:"interactive"};
  const offline={name:"unique-beta",baseUrl:"http://100.78.106.121:19175",
    model, adapter:"openai", maxInflight:1, role:"interactive"};
  const completions=[];
  const fetchImpl=async (url,options)=>{
    if(url.endsWith("/v1/models")) return Response.json({data:[{id:model}]});
    const body=JSON.parse(options.body);
    completions.push({url,question:body.messages.at(-1).content});
    if(url.includes("100.78.106.121"))throw Error("beta temporarily unavailable");
    return Response.json({choices:[{message:{content:"successfully analyzed"}}]});
  };
  const result=await runParallelLFM3Research({...args,authorized:true,
    nodes:[primary,offline],fetchImpl});
  assert.equal(result.status,503);
  assert.match(result.error,/worker was unavailable/);
  assert.equal(completions.filter(x=>x.question.includes("Answer this question using")).length,0,
    "no synthesis should run when independent provenance failed");
});

test("aliases or different ports on one physical host are not independent workers", async () => {
  const one={...nodes[0],name:"gpu-alias-one"};
  const second={...nodes[0],name:"gpu-alias-two",baseUrl:"http://100.83.215.83:19176"};
  const {calls,fetchImpl}=transport();
  const result=await runParallelLFM3Research({...args,authorized:true,
    nodes:[one,second],fetchImpl});
  assert.equal(result.status,400);
  assert.match(result.error,/distinct physical fleet hosts/);
  assert.equal(calls.length,0,"the alias attack must be rejected before inference");
});
test("model results on different runtime names but one physical host cannot be synthesized", async () => {
  const physical={name:"one-gpu",baseUrl:"http://100.83.215.83:19175",
    model,adapter:"openai",maxInflight:1,role:"interactive"};
  const overflowAlias={name:"same-gpu-different-port",
    baseUrl:"http://100.83.215.83:19176",
    model,adapter:"openai",maxInflight:1,role:"interactive"};
  const observed=[];
  const fetchImpl=async (url,opts)=>{
    observed.push(url);
    if(url.endsWith("/v1/models"))return Response.json({data:[{id:model}]});
    return Response.json({choices:[{message:{content:"model output"}}]});
  };
  const result=await runParallelLFM3Research({...args,authorized:true,
    nodes:[physical,overflowAlias],fetchImpl});
  assert.equal(result.status,400);
  assert.equal(observed.length,0);
});

test("preassigned GPUs use an unused OptiPlex CPU spare when one GPU fails", async () => {
  const first={...nodes[0],name:"reserve-r9700",role:"interactive"};
  const second={...nodes[1],name:"reserve-rx480",role:"interactive"};
  const spare={...nodes[0],name:"reserve-optiplex",
    baseUrl:"http://100.69.158.114:19176",role:"overflow"};
  const calls=[];
  const fetchImpl=async (url,opts)=>{
    if(url.endsWith("/v1/models"))return Response.json({data:[{id:model}]});
    const prompt=JSON.parse(opts.body).messages.at(-1).content;
    calls.push({url,prompt});
    if(url.includes("100.78.106.121"))throw Error("GPU model failed");
    return Response.json({choices:[{message:{content:"4"}}]});
  };
  const result=await runParallelLFM3Research({...args,authorized:true,
    nodes:[first,second,spare],fetchImpl});
  assert.equal(result.status,200);
  assert.deepEqual(result.workerRuntimes,["reserve-r9700","reserve-optiplex"]);
  assert.equal(calls.filter(x=>x.url.includes("100.78.106.121")).length,1);
  assert.equal(calls.filter(x=>x.url.includes("100.69.158.114")).length,1);
  assert.equal(new Set(result.workerRuntimes).size,2);
  assert.equal(calls.filter(x=>x.prompt.includes("Answer this question using")).length,1);
});
test("three perspectives preassign distinct GPU/GPU/CPU hosts without collisions", async () => {
  const third={...nodes[0],name:"three-optiplex",role:"overflow",
    baseUrl:"http://100.69.158.114:19176"};
  const {fetchImpl}=transport();
  const result=await runParallelLFM3Research({
    ...args,authorized:true,nodes:[...nodes,third],
    subtasks:["Analyze throughput","Analyze memory","Analyze operational risk"],
    fetchImpl
  });
  assert.equal(result.status,200);
  assert.deepEqual(result.workerRuntimes,["parallel-alpha","parallel-beta","three-optiplex"]);
});
test("a busy GPU is not assigned to another parallel task, CPU can fill its slot", async () => {
  const first={...nodes[0],name:"busy-preassign-r9700",role:"interactive"};
  const second={...nodes[1],name:"busy-preassign-rx480",role:"interactive"};
  const spare={...nodes[0],name:"busy-preassign-optiplex",role:"overflow",
    baseUrl:"http://100.69.158.114:19176"};
  let started,release;
  const arrived=new Promise(resolve=>{started=resolve;});
  const held=new Promise(resolve=>{release=resolve;});
  const holderFetch=async url=>{
    if(url.endsWith("/v1/models"))return Response.json({data:[{id:model}]});
    started();
    await held;
    return Response.json({choices:[{message:{content:"occupied request complete"}}]});
  };
  const holding=completeFleetChat([{role:"user",content:"Hold one GPU slot"}],{
    nodes:[first],fetchImpl:holderFetch
  });
  try {
    await arrived;
    const calls=[];
    const fetchImpl=async (url,opts)=>{
      if(url.endsWith("/v1/models"))return Response.json({data:[{id:model}]});
      calls.push(url);
      return Response.json({choices:[{message:{content:"valid"}}]});
    };
    const result=await runParallelLFM3Research({...args,authorized:true,
      nodes:[first,second,spare],fetchImpl});
    assert.equal(result.status,200);
    assert.deepEqual(result.workerRuntimes,["busy-preassign-rx480","busy-preassign-optiplex"]);
    assert.equal(calls.some(url=>url.includes("100.83.215.83")),false);
  } finally {
    release();
    await holding;
  }
});
