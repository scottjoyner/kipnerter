import test from "node:test";
import assert from "node:assert/strict";
import { endpointConfig, isLoaded, completeFleetChat, validateMessages, fitNodeContext, discoverFleetNodes, fleetRuntimeSnapshot } from "../lib/lfm3-fleet.mjs";

const node = { name: "joyner", baseUrl: "http://100.83.215.83:1234", model: "liquid/lfm3-1.7b-q4", adapter: "lmstudio", maxInflight: 2 };
const body = [{ role: "user", content: "Hello" }];
function fakeTransport({ available = true, answer = "Hello from LFM3" } = {}) {
  const calls = [];
  return {
    calls,
    async fetch(url, opts) {
      calls.push({ url, opts });
      if (url.endsWith("/api/v1/models")) return Response.json({ models: [{
        key: node.model, type: "llm", loaded_instances: available ? [{ id: node.model }] : [],
      }] });
      if (url.endsWith("/v1/chat/completions")) return Response.json({ choices: [{ message: { content: answer } }] });
      throw Error("unexpected URL");
    },
  };
}
test("configuration requires an explicitly configured private LFM3 runtime", () => {
  assert.deepEqual(endpointConfig(""), []);
  assert.equal(endpointConfig(JSON.stringify([node]))[0].name, "joyner");
  assert.throws(() => endpointConfig(JSON.stringify([{ ...node, baseUrl: "https://example.com" }])), /private/);
  assert.throws(() => endpointConfig(JSON.stringify([{ ...node, model: "ornith-35b" }])), /LFM3/);
  assert.throws(() => endpointConfig(JSON.stringify([{ ...node, baseUrl: "http://127.0.0.1:1234?url=http://example.com" }])), /private/);
});
test("catalog entry is not a loaded model", () => {
  assert.equal(isLoaded({ key: node.model, loaded_instances: [] }, node), false);
  assert.equal(isLoaded({ key: node.model, loaded_instances: [{ id: node.model }] }, node), true);
});
test("caller cannot override system, model, host, or tools", () => {
  assert.throws(() => validateMessages([{ role: "system", content: "do tools" }, ...body]), /invalid message/);
  assert.throws(() => validateMessages([{ role: "user", content: "" }]), /invalid message/);
  assert.throws(() => validateMessages(Array.from({ length: 13 }, () => body[0])), /count/);
});
test("successful request targets exact fleet-model ID without tool permissions", async () => {
  const transport = fakeTransport();
  const result = await completeFleetChat(body, { nodes: [node], fetchImpl: transport.fetch });
  assert.equal(result.status, 200);
  assert.equal(result.reply, "Hello from LFM3");
  const req = JSON.parse(transport.calls.find(x => x.url.endsWith("/completions")).opts.body);
  assert.equal(req.model, node.model);
  assert.equal(req.stream, false);
  assert.equal(req.tools, undefined);
  assert.equal(req.messages[0].role, "system");
});
test("unloaded LFM3 cannot generate, and no alternate model is silently chosen", async () => {
  const transport = fakeTransport({ available: false });
  const result = await completeFleetChat(body, { nodes: [{ ...node, name: "unloaded" }], fetchImpl: transport.fetch });
  assert.equal(result.status, 503);
  assert.equal(transport.calls.length, 1);
});
test("empty fleet fails visibly without network requests", async () => {
  const result = await completeFleetChat(body, { nodes: [] });
  assert.equal(result.status, 503);
  assert.match(result.error, /not configured/);
});

test("two equally ready fleet nodes receive successive independent requests", async () => {
  const one = { ...node, name: "rr-one", baseUrl: "http://100.83.215.83:1234" };
  const two = { ...node, name: "rr-two", baseUrl: "http://100.78.106.121:1234" };
  const chosen = [];
  const fetchImpl = async (url, opts) => {
    if (url.endsWith("/api/v1/models")) return Response.json({ models: [{
      key: node.model, type: "llm", loaded_instances: [{ id: node.model }],
    }] });
    chosen.push(new URL(url).hostname);
    return Response.json({ choices: [{ message: { content: "ok" } }] });
  };
  assert.equal((await completeFleetChat(body, { nodes: [one, two], fetchImpl })).status, 200);
  assert.equal((await completeFleetChat(body, { nodes: [one, two], fetchImpl })).status, 200);
  assert.equal(new Set(chosen).size, 2, "a free healthy node must not monopolize sequential requests");
});
test("an unavailable LFM3 node fails over to another LFM3 node only", async () => {
  const failing = { ...node, name: "fail-node", baseUrl: "http://100.78.106.121:1234" };
  const working = { ...node, name: "good-node", baseUrl: "http://100.83.215.83:1234" };
  const transport = async (url) => {
    if (url.includes("100.78.106.121")) throw Error("unreachable");
    if (url.endsWith("/api/v1/models")) return Response.json({ models: [{
      key: node.model, type: "llm", loaded_instances: [{ id: node.model }],
    }] });
    return Response.json({ choices: [{ message: { content: "LFM3 on fallback" } }] });
  };
  const result = await completeFleetChat(body, { nodes: [failing, working], fetchImpl: transport });
  assert.equal(result.status, 200);
  assert.equal(result.runtime, "good-node");
});

test("per-node token env references must be server-scoped", () => {
  const configured = endpointConfig(JSON.stringify([{ ...node, credentialEnv: "KIPNERTER_LFM3_TOKEN_JOYNER" }]));
  assert.equal(configured[0].credentialEnv, "KIPNERTER_LFM3_TOKEN_JOYNER");
  assert.throws(() => endpointConfig(JSON.stringify([{ ...node, credentialEnv: "NEXT_PUBLIC_LEAK" }])), /credential/);
});
test("different nodes use different bearer tokens for their catalog and generation requests", async () => {
  const one = { ...node, name: "authA", credentialEnv: "KIPNERTER_LFM3_TOKEN_A" };
  const two = { ...node, name: "authB", baseUrl: "http://100.78.106.121:1234", credentialEnv: "KIPNERTER_LFM3_TOKEN_B" };
  const requests = [];
  const fetchImpl = async (url, opts) => {
    requests.push([url, opts.headers.Authorization]);
    if (url.endsWith("/api/v1/models"))
      return Response.json({ models: [{ key: node.model, type: "llm", loaded_instances: [{id:node.model}] }] });
    return Response.json({choices:[{message:{content:"okay"}}]});
  };
  const resolveToken = entry => entry.name === "authA" ? "private-A" : "private-B";
  for (let i = 0; i < 2; i++) {
    const result = await completeFleetChat(body, { nodes: [one, two], resolveToken, fetchImpl });
    assert.equal(result.status, 200);
  }
  assert.deepEqual(new Set(requests.map(([url, auth]) => auth)), new Set(["Bearer private-A", "Bearer private-B"]));
  for (const [url, auth] of requests) {
    assert.equal(auth, url.includes("100.78.106.121") ? "Bearer private-B" : "Bearer private-A");
  }
});
test("missing required per-node credential fails closed without network requests", async () => {
  const calls = [];
  const result = await completeFleetChat(body, {
    nodes: [{ ...node, name: "no-auth", credentialEnv: "KIPNERTER_LFM3_TOKEN_MISSING" }],
    resolveToken: () => "", fetchImpl: async (...args) => { calls.push(args); throw Error("should never request"); },
  });
  assert.equal(result.status, 503);
  assert.equal(calls.length, 0);
});

test("interactive GPU nodes take precedence over lower-priority CPU overflow nodes", async () => {
  const cpu = { ...node, name: "overflow-cpu", baseUrl: "http://100.69.158.114:19176", role: "overflow" };
  const gpu = { ...node, name: "interactive-gpu", baseUrl: "http://100.78.106.121:19176", role: "interactive" };
  const transport = fakeTransport();
  const result = await completeFleetChat(body, { nodes: [cpu, gpu], fetchImpl: transport.fetch });
  assert.equal(result.status, 200);
  assert.equal(result.runtime, "interactive-gpu");
  assert.equal(transport.calls.filter(c => c.url.endsWith("/v1/chat/completions")).length, 1);
});
test("overflow CPU is eligible if all interactive nodes are unavailable", async () => {
  const gpu = { ...node, name: "failed-gpu", baseUrl: "http://100.78.106.121:19176", role: "interactive" };
  const cpu = { ...node, name: "rescue-cpu", baseUrl: "http://100.69.158.114:19176", role: "overflow" };
  let cpuMaxTokens;
  const fetchImpl = async (url, options) => {
    if (url.includes("100.78.106.121")) throw Error("offline");
    if (url.endsWith("/api/v1/models"))
      return Response.json({ models: [{ key: node.model, type: "llm", loaded_instances: [{ id: node.model }] }] });
    cpuMaxTokens = JSON.parse(options.body).max_tokens;
    return Response.json({ choices: [{ message: { content: "CPU response" } }] });
  };
  const result = await completeFleetChat(body, { nodes: [cpu, gpu], fetchImpl });
  assert.equal(result.status, 200);
  assert.equal(result.runtime, "rescue-cpu");
  assert.equal(cpuMaxTokens, 256, "CPU output should be bounded to protect latency");
});
test("endpoint configuration requires a known routing role", () => {
  const parsed = endpointConfig(JSON.stringify([{ ...node, role: "overflow" }]));
  assert.equal(parsed[0].role, "overflow");
  assert.equal(endpointConfig(JSON.stringify([node]))[0].role, "interactive");
  assert.throws(() => endpointConfig(JSON.stringify([{ ...node, role: "agent-command" }])), /role/);
});

test("only recent contiguous conversation turns reach small LFM3 inference contexts", () => {
  const history = Array.from({ length: 10 }, (_, i) => ({
    role: i % 2 ? "assistant" : "user",
    content: "turn " + i + " " + "x".repeat(1400),
  }));
  history.push({ role: "user", content: "What is the answer?" });
  const selected = validateMessages(history);
  assert.equal(selected[0].role, "system");
  assert.equal(selected.at(-1).content, "What is the answer?");
  assert.ok(selected.length < history.length + 1, "older turns must be dropped");
  assert.ok(selected.length > 2, "recent context should be preserved");
  const indexOfSelected = history.findIndex(entry => entry.content === selected[1].content);
  assert.deepEqual(selected.slice(1), history.slice(indexOfSelected));
});
test("oversized final Unicode prompt is rejected, not truncated", () => {
  assert.throws(() => validateMessages([{ role: "user", content: "界".repeat(3000) }]), /context budget/);
});

test("per-node budgets preserve the newest turn and fit CPU overflow context", () => {
  const history = validateMessages([
    {role:"user",content:"a".repeat(410)},
    {role:"assistant",content:"b".repeat(410)},
    {role:"user",content:"what is 2+2?"}
  ]);
  const gpu = fitNodeContext(history,{role:"interactive"});
  const cpu = fitNodeContext(history,{role:"overflow"});
  assert.equal(gpu.at(-1).content,"what is 2+2?");
  assert.equal(cpu.at(-1).content,"what is 2+2?");
  assert.ok(gpu.length > cpu.length, "GPU can preserve more context than CPU");
  assert.ok(new TextEncoder().encode(cpu.map(m=>m.content).join("")).length < 900);
});
test("CPU must not silently truncate a latest turn larger than its context budget", () => {
  const messages=validateMessages([{role:"user",content:"x".repeat(1000)}]);
  assert.equal(fitNodeContext(messages,{role:"overflow"}),null);
  assert.equal(fitNodeContext(messages,{role:"interactive"}).at(-1).content.length,1000);
});
test("long GPU conversation may fail over to CPU only with fitting recent turns", async () => {
  const gpu={...node,name:"long-gpu",baseUrl:"http://100.78.106.121:19176",role:"interactive"};
  const cpu={...node,name:"long-cpu",baseUrl:"http://100.69.158.114:19176",role:"overflow"};
  let cpuBody;
  const fetchImpl=async (url,options)=>{
    if(url.includes("100.78.106.121"))throw Error("offline");
    if(url.endsWith("/api/v1/models"))return Response.json({models:[{key:node.model,type:"llm",loaded_instances:[{id:node.model}]}]});
    cpuBody=JSON.parse(options.body);
    return Response.json({choices:[{message:{content:"4"}}]});
  };
  const history=Array.from({length:8},(_,i)=>({role:i%2?"assistant":"user",content:"turn-"+i+" "+"z".repeat(350)}));
  history.push({role:"user",content:"Answer 2+2."});
  const result=await completeFleetChat(history,{nodes:[gpu,cpu],fetchImpl});
  assert.equal(result.status,200);
  assert.equal(result.runtime,"long-cpu");
  assert.equal(cpuBody.messages.at(-1).content,"Answer 2+2.");
  assert.ok(cpuBody.messages.length < history.length);
  assert.equal(cpuBody.max_tokens,256);
});

test("R9700 can opt out of reasoning while retaining exact LFM3 model identity", async () => {
  const gpu = { ...node, name: "r9700", model: "lfm3-1.7b-research",
    adapter: "openai", maxInflight: 1, disableThinking: true, maxOutputTokens: 256 };
  const configured = endpointConfig(JSON.stringify([gpu]))[0];
  let generated;
  const fetchImpl = async (url, opts) => {
    if (url.endsWith("/v1/models")) {
      return Response.json({data:[{id:configured.model}]});
    }
    generated = JSON.parse(opts.body);
    return Response.json({choices:[{message:{content:"4"}}]});
  };
  const result = await completeFleetChat(body, {nodes:[configured],fetchImpl});
  assert.equal(result.status,200);
  assert.equal(result.reply,"4");
  assert.equal(generated.model,"lfm3-1.7b-research");
  assert.deepEqual(generated.chat_template_kwargs,{enable_thinking:false});
  assert.equal(generated.max_tokens,256);
  assert.equal(generated.tools,undefined);
});
test("existing RX480 and OptiPlex models retain default generation settings", async () => {
  const gpu = { ...node, name:"rx480-thinking-default", adapter:"openai",
    model:"lfm3-1.7b-rx480", maxInflight:1 };
  let generated;
  const fetchImpl = async (url, opts) => {
    if (url.endsWith("/v1/models")) return Response.json({data:[{id:gpu.model}]});
    generated = JSON.parse(opts.body);
    return Response.json({choices:[{message:{content:"ready"}}]});
  };
  const result = await completeFleetChat(body, {nodes:[endpointConfig(JSON.stringify([gpu]))[0]], fetchImpl});
  assert.equal(result.status,200);
  assert.equal(generated.chat_template_kwargs,undefined);
  assert.equal(generated.max_tokens,512);
});
test("endpoint generation settings are tightly bounded and typed", () => {
  for (const disableThinking of ["false",1,null]) {
    assert.throws(() => endpointConfig(JSON.stringify([{...node,disableThinking}])),/generation policy/);
  }
  for (const maxOutputTokens of [0,17,513,128.5,"256"]) {
    assert.throws(() => endpointConfig(JSON.stringify([{...node,maxOutputTokens}])),/generation policy/);
  }
  assert.equal(endpointConfig(JSON.stringify([{...node,maxOutputTokens:192}]))[0].maxOutputTokens,192);
});

test("private discovery distinguishes native loaded weights from OpenAI catalog listing", async () => {
  const native = { ...node, name: "native-loaded-discovery" };
  const openai = { ...node, name: "openai-catalog-discovery", adapter: "openai",
    baseUrl: "http://100.78.106.121:19176", role: "overflow", maxInflight: 1 };
  const fetchImpl = async (url) => {
    if (url.endsWith("/api/v1/models")) return Response.json({models: [{
      key: native.model, type: "llm", loaded_instances:[{id:native.model}]
    }]});
    return Response.json({data:[{id:openai.model}]});
  };
  const result = await discoverFleetNodes([native,openai], {fetchImpl});
  assert.deepEqual(result.map(x=>x.state),["loaded","catalog-listed"]);
  assert.equal(result[1].role,"overflow");
  assert.equal(result[1].maxInflight,1);
  assert.equal(JSON.stringify(result).includes("100.78.106.121"),false, "no private node IP returned");
});
test("uncredentialed or unreachable discovery cannot qualify a candidate", async () => {
  const locked={ ...node, name:"needs-key", credentialEnv:"KIPNERTER_LFM3_TOKEN_MISSING" };
  const offline={ ...node, name:"offline-discovery", credentialEnv:null };
  let requests=0;
  const states=await discoverFleetNodes([locked,offline], {
    resolveToken: () => "",
    fetchImpl:async () => {requests++;throw Error("unreachable");}
  });
  assert.deepEqual(states.map(x=>x.state),["missing-credential","unavailable"]);
  assert.equal(requests,1);
});
test("a successful actual generation upgrades only that candidate to served in-process", async () => {
  const n={...node,name:"actually-served-discovery",adapter:"openai",baseUrl:"http://100.83.215.83:19176"};
  const fetchImpl=async (url)=>{
    if(url.endsWith("/v1/models"))return Response.json({data:[{id:n.model}]});
    return Response.json({choices:[{message:{content:"4"}}]});
  };
  assert.equal((await discoverFleetNodes([n],{fetchImpl}))[0].state,"catalog-listed");
  const generated=await completeFleetChat(body,{nodes:[n],fetchImpl});
  assert.equal(generated.status,200);
  const found=await discoverFleetNodes([n],{fetchImpl});
  assert.equal(found[0].state,"served");
  assert.match(found[0].lastSuccessAt,/^\d{4}-\d\d-\d\dT/);
});

test("actual generation records recent latency while releasing the worker slot", async () => {
  const candidate={...node,name:"telemetry-gpu",adapter:"openai",model:"lfm3-1.7b-telemetry",
    maxInflight:1};
  const fetchImpl=async url => url.endsWith("/v1/models")
    ? Response.json({data:[{id:candidate.model}]})
    : Response.json({choices:[{message:{content:"one generated answer"}}]});
  const before=fleetRuntimeSnapshot(candidate);
  assert.equal(before.inFlight,0);
  assert.equal(before.lastLatencyMs,null);
  const response=await completeFleetChat(body,{nodes:[candidate],fetchImpl});
  assert.equal(response.status,200);
  const after=fleetRuntimeSnapshot(candidate);
  assert.equal(after.inFlight,0);
  assert.equal(after.cooldown,false);
  assert.ok(Number.isInteger(after.lastLatencyMs));
  assert.ok(after.lastLatencyMs >= 0);
  const discovered=await discoverFleetNodes([candidate],{fetchImpl});
  assert.equal(discovered[0].state,"served");
  assert.equal(discovered[0].lastLatencyMs,after.lastLatencyMs);
});
test("private discovery reports live in-flight leases without exposing credentials", async () => {
  const candidate={...node,name:"concurrent-lease-lfm3",adapter:"openai",
    model:"lfm3-1.7b-lease",maxInflight:1,credentialEnv:null};
  let proceed;
  let started;
  const waiting=new Promise(resolve=>{proceed=resolve;});
  const arrived=new Promise(resolve=>{started=resolve;});
  const fetchImpl=async url=>{
    if(url.endsWith("/v1/models"))return Response.json({data:[{id:candidate.model}]});
    started();
    await waiting;
    return Response.json({choices:[{message:{content:"Lease released"}}]});
  };
  const generating=completeFleetChat(body,{nodes:[candidate],fetchImpl});
  await arrived;
  assert.equal(fleetRuntimeSnapshot(candidate).inFlight,1);
  const during=await discoverFleetNodes([candidate],{fetchImpl});
  assert.equal(during[0].inFlight,1);
  const busy=await completeFleetChat(body,{nodes:[candidate],fetchImpl});
  assert.equal(busy.status,503);
  proceed();
  assert.equal((await generating).status,200);
  assert.equal(fleetRuntimeSnapshot(candidate).inFlight,0);
});
test("failed generation opens a bounded circuit-breaker cooldown", async () => {
  const candidate={...node,name:"circuit-breaker-lfm3",adapter:"openai",
    model:"lfm3-1.7b-circuit",maxInflight:1};
  let calls=0;
  const fetchImpl=async url=>{
    calls++;
    if(url.endsWith("/v1/models"))return Response.json({data:[{id:candidate.model}]});
    throw Error("inference worker unavailable");
  };
  const first=await completeFleetChat(body,{nodes:[candidate],fetchImpl});
  assert.equal(first.status,503);
  assert.equal(fleetRuntimeSnapshot(candidate).cooldown,true);
  assert.equal(fleetRuntimeSnapshot(candidate).inFlight,0);
  const count=calls;
  const second=await completeFleetChat(body,{nodes:[candidate],fetchImpl});
  assert.equal(second.status,503);
  assert.equal(calls,count,"cooling down must avoid repeated upstream requests");
});

test("oversized newest turn fails before GPU or CPU lookup instead of misreporting outage", async () => {
  const gpu={...node,name:"preflight-size-gpu",adapter:"openai",role:"interactive"};
  const cpu={...node,name:"preflight-size-cpu",adapter:"openai",role:"overflow"};
  let requests=0;
  const result=await completeFleetChat([
    {role:"user",content:"a".repeat(2000)}
  ],{nodes:[gpu,cpu],fetchImpl:async()=>{requests++;throw Error("never called");}});
  assert.equal(result.status,413);
  assert.match(result.error,/latest message exceeds/i);
  assert.equal(requests,0,"no model catalog or generation calls for an unfit prompt");
});
test("an otherwise too-long CPU request remains eligible for fitting GPU contexts", async () => {
  const gpu={...node,name:"preflight-fit-gpu",adapter:"openai",model:"lfm3-1.7b-preflight",role:"interactive"};
  const cpu={...node,name:"preflight-unfit-cpu",adapter:"openai",model:"lfm3-1.7b-preflight",role:"overflow"};
  const calls=[];
  const fetchImpl=async (url,opts)=>{
    calls.push(url);
    if(url.endsWith("/v1/models")) return Response.json({data:[{id:gpu.model}]});
    return Response.json({choices:[{message:{content:"valid"}}]});
  };
  const result=await completeFleetChat([{role:"user",content:"x".repeat(1000)}],{
    nodes:[cpu,gpu],fetchImpl
  });
  assert.equal(result.status,200);
  assert.equal(result.runtime,gpu.name);
  assert.equal(calls.filter(x=>x.includes("/chat/completions")).length,1);
});
