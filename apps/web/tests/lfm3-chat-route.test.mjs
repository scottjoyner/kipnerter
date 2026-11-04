import test from "node:test";
import assert from "node:assert/strict";
import { POST } from "../app/api/chat/completions/route.js";

function request(body, client = "route-test-client") {
  return new Request("https://kipnerter.com/api/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json", "x-real-ip": client },
    body,
    // Node's Fetch requires duplex for streamed request bodies.
    ...(body instanceof ReadableStream ? { duplex: "half" } : {}),
  });
}
test("chunked oversized anonymous chat fails at 48KB without Content-Length", async () => {
  const data = new TextEncoder().encode("x".repeat(49000));
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(data.subarray(0, 10000));
      controller.enqueue(data.subarray(10000));
      controller.close();
    },
  });
  const response = await POST(request(stream, "route-large-stream"));
  assert.equal(response.status, 413);
  assert.deepEqual(await response.json(), { error: "Request too large." });
});
test("invalid JSON is rejected without a fleet call", async () => {
  const response = await POST(request("{", "route-invalid-json"));
  assert.equal(response.status, 400);
});
test("server-only response rejects unknown client-supplied fleet controls", async () => {
  const response = await POST(request(JSON.stringify({
    messages: [{ role: "user", content: "Hello" }],
    baseUrl: "http://127.0.0.1:19176",
  }), "route-client-url"));
  assert.equal(response.status, 400);
});
test("valid bounded JSON still reaches configured-fleet readiness gate", async () => {
  const prior = process.env.KIPNERTER_LFM3_ENDPOINTS;
  delete process.env.KIPNERTER_LFM3_ENDPOINTS;
  try {
    const response = await POST(request(JSON.stringify({
      messages: [{ role: "user", content: "Hello" }],
    }), "route-valid-no-fleet"));
    assert.equal(response.status, 503);
    const result = await response.json();
    assert.match(result.error, /not configured/i);
  } finally {
    if (prior === undefined) delete process.env.KIPNERTER_LFM3_ENDPOINTS;
    else process.env.KIPNERTER_LFM3_ENDPOINTS = prior;
  }
});
