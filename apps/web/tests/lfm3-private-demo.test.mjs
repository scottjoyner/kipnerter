import test from "node:test";
import assert from "node:assert/strict";
import {
  runPrivateDemoAcceptance, inspectPrivateDemoContainer, DEMO_CONTAINER,
} from "../../../deploy/lfm3/private-demo-acceptance.mjs";

const known = { keyStatus: "ready", rosterReady: true, stage: true };
const invalid = { keyStatus: "missing", rosterReady: true, stage: true };
function fixture({ model = "LFM3-1.7B", reply = "4", status = 200 } = {}) {
  const calls = [];
  const fetchImpl = async (url, request) => {
    calls.push({ url, ...request });
    if (url.endsWith("/api/chat/completions")) {
      const data = JSON.parse(request.body);
      assert.deepEqual(Object.keys(data), ["messages"]);
      assert.equal(data.messages.length, 1);
      assert.equal(data.messages[0].role, "user");
      return data.messages[0].content.length >= 2000 ?
        Response.json({ error: "too large" }, { status: 413 }) :
        Response.json({ model, reply }, { status });
    }
    return new Response("<div>Message Kipnerter LFM3-1.7B</div>", { status: 200 });
  };
  return { fetchImpl, calls };
}
test("demo requires exactly one approved RX480 worker before any HTTP call", async () => {
  let calls = 0;
  const result = await runPrivateDemoAcceptance({
    inspect: () => invalid, fetchImpl: () => { calls++; throw Error("must not call"); },
  });
  assert.equal(result.decision, "HOLD");
  assert.equal(result.keyStatus, "missing");
  assert.equal(calls, 0);
});
test("approved private single-worker fixture produces DEMO_PASS, never production PASS", async () => {
  const { fetchImpl, calls } = fixture();
  const result = await runPrivateDemoAcceptance({ inspect: () => known, fetchImpl });
  assert.equal(result.decision, "DEMO_PASS");
  assert.equal(result.scope, "single-worker-loopback-only");
  assert.equal(result.model, "LFM3-1.7B");
  assert.equal(calls.length, 4);
  assert.equal(calls.filter(x=>x.method === "POST").length, 2);
  assert.ok(calls.every(x => x.redirect === "error"));
});
test("wrong LFM family or blank reply never passes the private demo", async () => {
  for (const problem of [{ model: "LFM2.5-1.2B" }, { reply: "" }, { status: 503 }]) {
    const { fetchImpl } = fixture(problem);
    const result = await runPrivateDemoAcceptance({ inspect: () => known, fetchImpl });
    assert.notEqual(result.decision, "DEMO_PASS");
  }
});
test("untrusted host or port fails before calling metadata or fetch", async () => {
  for (const url of ["https://kipnerter.com", "http://localhost:3356",
    "http://127.0.0.1:3354", "http://127.0.0.1:3356/chat",
    "http://127.0.0.1:3356/?x=y", "http://0.0.0.0:3356"]) {
    const result = await runPrivateDemoAcceptance({
      url, inspect: () => { throw Error("must not inspect"); },
      fetchImpl: () => { throw Error("must not fetch"); },
    });
    assert.equal(result.decision, "FAIL", url);
  }
});
test("Docker metadata inspector validates container identity and outputs no secret", () => {
  let captured = null;
  const exec = (program, args) => {
    captured = [program, ...args];
    return JSON.stringify(known);
  };
  assert.deepEqual(inspectPrivateDemoContainer(DEMO_CONTAINER, { exec }), known);
  assert.equal(captured[0], "docker");
  assert.equal(captured[1], "exec");
  assert.equal(captured[2], DEMO_CONTAINER);
  assert.throws(() => inspectPrivateDemoContainer(DEMO_CONTAINER + ";whoami", {exec}), /unexpected/);
});

test("single-worker demo compose cannot advertise a public socket or fabricate a 3-worker release", async () => {
  const { readFileSync } = await import("node:fs");
  const source = readFileSync(new URL("../../../deploy/lfm3/compose.demo-rx480.yml", import.meta.url), "utf8");
  assert.match(source, /127\.0\.0\.1:3356:3000/);
  assert.match(source, /create_host_path: false/);
  assert.match(source, /read_only: true/);
  assert.match(source, /restart: "no"/);
  assert.match(source, /external: true/);
  assert.doesNotMatch(source, /(?:^|\n)\s+-\s*["']?0\.0\.0\.0:/);
  assert.doesNotMatch(source, /Bearer\s+[A-Za-z0-9]+/);
  const raw = source.match(/KIPNERTER_LFM3_ENDPOINTS:\s*>-\s*\n\s*(\[[^\n]+\])/);
  assert.ok(raw, "explicit JSON roster required");
  const nodes = JSON.parse(raw[1]);
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].name, "rx480");
  assert.equal(nodes[0].model, "lfm3-1.7b-rx480");
  assert.equal(nodes[0].credentialEnv, "KIPNERTER_LFM3_TOKEN_RX480");
  assert.equal(nodes[0].baseUrl, "http://100.78.106.121:19176");
});
