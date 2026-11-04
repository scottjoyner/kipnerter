import test from "node:test";
import assert from "node:assert/strict";
import { endpointConfig, isLoaded, completeFleetChat, validateMessages } from "../lib/lfm3-fleet.mjs";

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