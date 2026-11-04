import test from "node:test";
import assert from "node:assert/strict";
import {
  inspectStagedSecretMounts, runGatewayAcceptance,
} from "../../../deploy/lfm3/gateway-acceptance.mjs";

const ready = { r9700: "ready", rx480: "ready", optiplex: "ready" };
function fakeTransport({ model = "LFM3-1.7B", reply = "4", status = 200 } = {}) {
  const calls = [];
  const fetchImpl = async (url, opts) => {
    calls.push({ url, method: opts.method, redirect: opts.redirect });
    if (url.endsWith("/api/chat/completions")) {
      const request = JSON.parse(opts.body);
      const input = request.messages[0].content;
      return input.length === 2000
        ? Response.json({ error: "too large" }, { status: 413 })
        : Response.json({ model, reply }, { status });
    }
    return new Response("staged", { status: 200 });
  };
  return { calls, fetchImpl };
}

test("missing private mounts HOLD before a generation, without touching any GPU", async () => {
  const { calls, fetchImpl } = fakeTransport();
  const result = await runGatewayAcceptance({
    url: "http://127.0.0.1:3353", fetchImpl,
    inspectSecrets: () => ({ r9700: "missing", rx480: "missing", optiplex: "missing" }),
  });
  assert.equal(result.decision, "HOLD");
  assert.equal(result.gate, "protected-model-secrets");
  assert.deepEqual(result.workerMounts, {
    r9700: "missing", rx480: "missing", optiplex: "missing",
  });
  assert.equal(calls.length, 2, "only homepage and pre-auth 413 are permitted");
});

test("staged authenticated model success passes and exposes no credential values", async () => {
  const { calls, fetchImpl } = fakeTransport();
  const result = await runGatewayAcceptance({
    url: "http://127.0.0.1:3353", fetchImpl, inspectSecrets: async () => ready,
  });
  assert.equal(result.decision, "PASS");
  assert.equal(result.gate, "authenticated-staged-chat");
  assert.equal(result.model, "LFM3-1.7B");
  assert.equal(calls.length, 3);
  assert.ok(calls.every(x => x.redirect === "error"));
  assert.equal(JSON.stringify(result).includes("Bearer"), false);
});

test("wrong model, blank reply, or model error never qualify", async () => {
  for (const problem of [
    { model: "LFM2.5-1.2B" }, { reply: "  \n " }, { status: 503 },
  ]) {
    const { fetchImpl } = fakeTransport(problem);
    const result = await runGatewayAcceptance({
      url: "http://127.0.0.1:3353", fetchImpl,
      inspectSecrets: () => ready,
    });
    assert.notEqual(result.decision, "PASS");
  }
});

test("untrusted origin, externally exposed stage URL, or path fails without fetch", async () => {
  let calls = 0;
  for (const url of [
    "https://127.0.0.1:3353", "http://kipnerter.com:3353",
    "http://100.82.144.33:3353", "http://127.0.0.1:3353/other",
    "http://127.0.0.1:4444", "http://localhost:3353",
  ]) {
    const result = await runGatewayAcceptance({
      url, fetchImpl: () => { calls++; throw Error("must not fetch"); },
      inspectSecrets: () => ready,
    });
    assert.equal(result.decision, "FAIL", url);
  }
  assert.equal(calls, 0);
});

test("inside-container secret inspection only uses private metadata and rejects name injection", () => {
  const received = [];
  const exec = (file, args) => {
    received.push([file, ...args]);
    return JSON.stringify(ready);
  };
  assert.deepEqual(inspectStagedSecretMounts("kipnerter-lfm3-stage-1f2f788", { exec }), ready);
  assert.equal(received.length, 1);
  assert.equal(received[0][0], "docker");
  assert.equal(received[0][1], "exec");
  assert.throws(() => inspectStagedSecretMounts("kipnerter-lfm3-stage-1f2f788;echo BAD", { exec }),
    /invalid staging/);
  assert.equal(received.length, 1);
});
