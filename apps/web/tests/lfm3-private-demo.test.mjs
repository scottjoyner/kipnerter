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
