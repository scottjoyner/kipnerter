import test from "node:test";
import assert from "node:assert/strict";
import { runParallelLFM3Research, fitResearchSynthesis } from "../lib/lfm3-parallel.mjs";
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
  // Use independent state keys: a prior negative test deliberately leaves a
  // different worker in circuit-breaker cooldown.
  const gpu1={...nodes[0],name:"three-r9700",role:"interactive"};
  const gpu2={...nodes[1],name:"three-rx480",role:"interactive"};
  const cpu={...nodes[0],name:"three-optiplex",role:"overflow",
    baseUrl:"http://100.69.158.114:19176"};
  const {fetchImpl}=transport();
  const result=await runParallelLFM3Research({
    ...args,authorized:true,nodes:[gpu1,gpu2,cpu],
    subtasks:["Analyze throughput","Analyze memory","Analyze operational risk"],
    fetchImpl
  });
  assert.equal(result.status,200);
  assert.deepEqual(result.workerRuntimes,["three-r9700","three-rx480","three-optiplex"]);
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

test("long independent responses are budgeted before synthesis without losing the question", async () => {
  const first={...nodes[0],name:"context-long-gpu-one",role:"interactive"};
  const second={...nodes[1],name:"context-long-gpu-two",role:"interactive"};
  const calls=[];
  const question="Evaluate a detailed scientific comparison of three candidate systems";
  const fetchImpl=async (url,options)=>{
    if(url.endsWith("/v1/models"))return Response.json({data:[{id:model}]});
    const prompt=JSON.parse(options.body).messages.at(-1).content;
    calls.push(prompt);
    const answer=prompt.startsWith("Answer this question using")
      ? "The results agree, with some uncertainty."
      : "Compute and compare. ".repeat(105);
    return Response.json({choices:[{message:{content:answer}}]});
  };
  const result=await runParallelLFM3Research({
    ...args,authorized:true,question,nodes:[first,second],fetchImpl
  });
  assert.equal(result.status,200);
  assert.equal(calls.length,3);
  const synthesis=calls.at(-1);
  assert.match(synthesis,/Answer this question using/);
  assert.ok(synthesis.includes(question));
  assert.match(synthesis,/Worker 1:/);
  assert.match(synthesis,/Worker 2:/);
  assert.ok(synthesis.length < 1100, "must use limited synthesis budget");
  assert.equal((synthesis.match(/Worker /g)||[]).length,2);
});

test("three large UTF8 research summaries fit one configured GPU synthesis context", async () => {
  const workers=Array.from({length:3},()=>({
    reply:"scientific perspective 🌎🔬 corroborating ".repeat(40)
  }));
  const cpu={...nodes[0],name:"synthesis-overflow-cpu",role:"overflow"};
  const gpu={...nodes[0],name:"synthesis-gpu",role:"interactive"};
  const question="Q ".repeat(140);
  const synthesis=fitResearchSynthesis(question,workers,[cpu,gpu]);
  assert.ok(synthesis, "synthesis should cap snippets against a real GPU context");
  assert.ok(synthesis.includes(question));
  assert.equal((synthesis.match(/Worker /g)||[]).length,3);
  assert.ok(Buffer.byteLength(synthesis,"utf8") < 1100);
  assert.equal(synthesis.includes("�"),false, "never split Unicode surrogate pairs");
});

test("CPU-only oversized research preflights synthesis before burning model requests", async () => {
  const cpuOne={...nodes[0],name:"long-research-cpu-one",role:"overflow"};
  const cpuTwo={...nodes[1],name:"long-research-cpu-two",role:"overflow"};
  let requests=0;
  const question="Z".repeat(690);
  assert.equal(fitResearchSynthesis(question,[
    {reply:"A minimum independent model summary."},
    {reply:"Another independent model summary."},
  ],[cpuOne,cpuTwo]),null);
  const result=await runParallelLFM3Research({...args,authorized:true,question,
    nodes:[cpuOne,cpuTwo],fetchImpl:async()=>{requests++;throw Error("must not call");}});
  assert.equal(result.status,413);
  assert.equal(requests,0,"must not issue catalog or generation calls if synthesis cannot fit");
  assert.match(result.error,/synthesis context/);
});

const shortTimeouts = { totalMs: 120, fanoutMs: 25, spareMs: 25, synthesisMs: 25 };
async function waitForAbort(signal) {
  if (signal.aborted) return;
  await new Promise(resolve => signal.addEventListener("abort", resolve, { once: true }));
}

test("slow GPU worker ends with bounded 504 and no synthesis or CPU overload", async () => {
  const gpuA = { ...nodes[0], name:"budget-fanout-r9700", role:"interactive" };
  const gpuB = { ...nodes[1], name:"budget-fanout-rx480", role:"interactive" };
  const requests = [];
  const fetchImpl = async (url,opts) => {
    if(url.endsWith("/v1/models")) return Response.json({data:[{id:model}]});
    requests.push(url);
    if(url.includes("100.78.106.121")) {
      await waitForAbort(opts.signal);
      throw Error("worker stopped at deadline");
    }
    return Response.json({choices:[{message:{content:"GPU A finished"}}]});
  };
  const started = Date.now();
  const result = await runParallelLFM3Research({
    ...args, authorized:true, nodes:[gpuA,gpuB],
    fetchImpl, timeoutPolicy:shortTimeouts,
  });
  assert.equal(result.status,504);
  assert.ok(Date.now()-started < 1000);
  assert.match(result.error,/time budget/);
  assert.equal(requests.filter(x=>x.includes("chat/completions")).length,2,
    "must never start synthesis after a fanout deadline");
});

test("CPU spare deadline cancels recovery without publishing partial research", async () => {
  const gpuA = { ...nodes[0], name:"budget-spare-r9700", role:"interactive" };
  const gpuB = { ...nodes[1], name:"budget-spare-rx480", role:"interactive" };
  const cpu = { ...nodes[0], name:"budget-spare-optiplex", role:"overflow",
    baseUrl:"http://100.69.158.114:19176" };
  const requests = [];
  const fetchImpl = async (url,opts) => {
    if(url.endsWith("/v1/models")) return Response.json({data:[{id:model}]});
    requests.push(url);
    if(url.includes("100.78.106.121")) throw Error("simulated failed GPU");
    if(url.includes("100.69.158.114")) {
      await waitForAbort(opts.signal);
      throw Error("CPU spare timed out");
    }
    return Response.json({choices:[{message:{content:"successful GPU"}}]});
  };
  const result = await runParallelLFM3Research({
    ...args,authorized:true,nodes:[gpuA,gpuB,cpu],
    fetchImpl,timeoutPolicy:shortTimeouts,
  });
  assert.equal(result.status,504);
  assert.equal(requests.filter(x=>x.includes("chat/completions")).length,3);
});

test("synthesis deadline cannot publish an unfinished final answer", async () => {
  const gpuA = { ...nodes[0], name:"budget-synth-r9700", role:"interactive" };
  const gpuB = { ...nodes[1], name:"budget-synth-rx480", role:"interactive" };
  let synthesisCalls = 0;
  const fetchImpl = async (url,opts) => {
    if(url.endsWith("/v1/models")) return Response.json({data:[{id:model}]});
    const msg = JSON.parse(opts.body).messages.at(-1).content;
    if(msg.startsWith("Answer this question using")) {
      synthesisCalls++;
      await waitForAbort(opts.signal);
      throw Error("synthesis timed out");
    }
    return Response.json({choices:[{message:{content:"Independent completed reasoning."}}]});
  };
  const result = await runParallelLFM3Research({
    ...args,authorized:true,nodes:[gpuA,gpuB],
    fetchImpl,timeoutPolicy:shortTimeouts,
  });
  assert.equal(result.status,504);
  assert.equal(synthesisCalls,1);
  assert.match(result.error,/time budget/);
});

test("client cancellation remains a distinct 499 response", async () => {
  const gpuA = { ...nodes[0], name:"budget-cancel-r9700", role:"interactive" };
  const gpuB = { ...nodes[1], name:"budget-cancel-rx480", role:"interactive" };
  const controller = new AbortController();
  const fetchImpl = async (url,opts) => {
    if(url.endsWith("/v1/models")) return Response.json({data:[{id:model}]});
    await waitForAbort(opts.signal);
    throw Error("user cancelled");
  };
  const operation = runParallelLFM3Research({
    ...args,authorized:true,nodes:[gpuA,gpuB],
    fetchImpl,signal:controller.signal,timeoutPolicy:shortTimeouts,
  });
  setTimeout(()=>controller.abort(),10);
  const result=await operation;
  assert.equal(result.status,499);
  assert.match(result.error,/cancelled/i);
});
