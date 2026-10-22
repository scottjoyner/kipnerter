import test from "node:test";
import assert from "node:assert/strict";
import { snapshotExpired, canApplyPoll, TELEMETRY_STALE_MS } from "../lib/telemetry-freshness.mjs";

test("snapshots older than 45 seconds expire instead of preserving green UI", () => {
  const start = 1730000000000;
  assert.equal(TELEMETRY_STALE_MS, 45000);
  assert.equal(snapshotExpired(start, start + 30000), false);
  assert.equal(snapshotExpired(start, start + 45000), false);
  assert.equal(snapshotExpired(start, start + 45001), true);
  assert.equal(snapshotExpired(0, start), false);
});
test("fallback fetch cannot overwrite subsequent SSE snapshot", () => {
  const priorPoll = 3;
  const currentGeneration = 4;  // new SSE snapshot arrived
  assert.equal(canApplyPoll(priorPoll, currentGeneration, false), false);
  assert.equal(canApplyPoll(currentGeneration, currentGeneration, false), true);
  assert.equal(canApplyPoll(currentGeneration, currentGeneration, true), false);
});
