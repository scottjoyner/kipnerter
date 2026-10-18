import test from "node:test";
import assert from "node:assert/strict";
import { boundedJson, abortableDelay } from "../lib/stream-utils.mjs";

test("bounded JSON accepts valid safe object and rejects bad body", async () => {
  assert.deepEqual(await boundedJson(Response.json({ status: "reported" })), { status: "reported" });
  await assert.rejects(boundedJson(Response.json([1,2])), /invalid telemetry/);
  await assert.rejects(boundedJson(new Response("{oops}", {status:200})), SyntaxError);
});
test("bounded JSON rejects lying content-length and oversized chunked body", async () => {
  await assert.rejects(
    boundedJson(new Response("123456789", {headers:{"content-length":"99999"}}), 16),
    /declared telemetry/
  );
  let consumed = 0;
  const response = new Response(new ReadableStream({
    pull(controller) {
      consumed++;
      controller.enqueue(new Uint8Array(2048).fill(32));
    },
    cancel() {},
  }));
  await assert.rejects(boundedJson(response, 4000), /streamed telemetry/);
  assert.ok(consumed < 20, "stream should stop early rather than buffering full response");
});
test("abortable sleep releases immediately on cancellation", async () => {
  const controller = new AbortController();
  const started = performance.now();
  const pending = abortableDelay(15000, controller.signal);
  controller.abort();
  assert.equal(await pending, false);
  assert.ok(performance.now() - started < 500);
  assert.equal(await abortableDelay(15000, controller.signal), false);
});
