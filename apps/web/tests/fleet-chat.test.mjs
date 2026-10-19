import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { answerFleetQuestion as ask } from "../lib/fleet-chat.mjs";

const fixture = {
  overview: { status: "live", integrations: [{ id: "assistx", status: "healthy" }, { id: "hermes", status: "unknown" }] },
  nodes: { status: "live", nodes: [{ name: "xwing", tailscale_online: true, inflight: 2 }, { name: "destroyer", tailscale_online: false }, { name: "lenovo", tailscale_online: null }] },
  models: { status: "reported", models: [{ id: "a", source: "lmstudio_native_catalog", loaded_instances: 1 }, { id: "b", source: "assistx_local_inventory", nodes: 0 }] },
  traces: { status: "historical", last_event_at: "2026-10-16T13:28:41Z", traces: [{ correlation_id: "safe" }] },
  sessions: { status: "reported", sessions: [{ agent: "hermes", id: "receipt-1", status: "COMPLETED" }] },
};
const options = { fresh: true, observedAt: "10:27 AM" };

test("read-only node summary preserves unknown Tailscale state", () => {
  assert.match(ask("Which nodes are online?", fixture, options), /3 nodes: 1 online, 1 offline, 1 unverified/);
  assert.match(ask("Is xwing online?", fixture, options), /xwing: Tailscale presence reported online/);
  assert.match(ask("What is the status of xwing?", fixture, options), /xwing: Tailscale presence reported online/);
});
test("models and traces cannot become independently verified by summarizing", () => {
  assert.match(ask("What models are loaded?", fixture, options), /reported loaded: 1/);
  assert.match(ask("What models are loaded?", fixture, options), /not.*proves?|Neither catalog presence/);
  assert.match(ask("Show traces", fixture, options), /source state: historical/);
  assert.match(ask("Show traces", fixture, options), /Polling freshness is not evidence/);
});
test("agent receipts and service health are attributed, not execution claims", () => {
  assert.match(ask("Show Hermes sessions", fixture, options), /launcher session receipts/);
  assert.match(ask("How is AssistX health?", fixture, options), /Auto-AssistX: healthy/);
});
test("missing or stale snapshots never report a healthy fleet", () => {
  assert.match(ask("What nodes are online?", fixture), /No fresh authenticated/);
  assert.match(ask("What models are loaded?", { models: { status: "unavailable" } }, options), /unknown/);
  assert.match(ask("What nodes are online?", { nodes: { status: "unavailable" } }, options), /unavailable/);
});
test("queries requesting effects cannot escape the read-only contract", () => {
  for (const question of ["ssh xwing", "restart fleet nodes", "deploy the API", "load the model", "sudo rm /", "dispatch Hermes", "run code on deathstar"]) {
    assert.match(ask(question, fixture, options), /cannot execute commands/);
  }
  assert.match(ask("", fixture, options), /Enter a question/);
  assert.match(ask("a".repeat(4001), fixture, options), /4,000/);
});
test("chat summarizer never opens a network or command transport", () => {
  const src = readFileSync(new URL("../lib/fleet-chat.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(src, /\b(fetch|WebSocket|EventSource|sendBeacon|localStorage|sessionStorage|indexedDB|child_process)\b/);
});
