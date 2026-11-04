import test from "node:test";
import assert from "node:assert/strict";
import { GET } from "../app/api/chat/fleet-status/route.js";

test("fleet discovery requires an authenticated authorized operator", async () => {
  const response = await GET();
  assert.ok([403, 503].includes(response.status));
  assert.equal(response.headers.get("Cache-Control"), "private, no-store");
  const payload = await response.json();
  assert.equal(typeof payload.error, "string");
  assert.equal(payload.workers, undefined);
});
