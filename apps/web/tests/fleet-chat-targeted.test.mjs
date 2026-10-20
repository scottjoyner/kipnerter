import test from "node:test";
import assert from "node:assert/strict";
import { answerFleetQuestion as ask } from "../lib/fleet-chat.mjs";

const opts = { fresh: true, observedAt: "10:30 AM" };
const fixture = {
  nodes: { status: "live", nodes: [
    { name: "xwing", tailscale_online: true, inflight: 2, models: ["Qwen Local", "Gemma Trial"] },
    { name: "xwing-dev", tailscale_online: null, models: ["dev-fixture"] },
    { name: "destroyer", tailscale_online: false, models: [] },
    { name: "lenovo", tailscale_online: null },
  ] },
  models: { status: "reported", models: [
    { name: "catalog-only", source: "assistx_local_inventory", loaded_instances: 0 },
  ] },
  traces: { status: "historical", traces: [{ correlation_id: "test-trace" }] },
  sessions: { status: "reported", sessions: [{ id: "receipt-1", agent: "hermes", status: "COMPLETE" }] },
};

test("targeted node model questions use node inventory, not fabricated residency", () => {
  const result = ask("What models are on xwing?", fixture, opts);
  assert.match(result, /xwing: 2 reported node model labels/);
  assert.match(result, /Qwen Local, Gemma Trial/);
  assert.match(result, /not verified loaded instances/);
  assert.doesNotMatch(result, /catalog-only/);
});

test("exact host tokens distinguish xwing from xwing-dev and reject substrings", () => {
  assert.match(ask("What models are on xwing-dev?", fixture, opts), /xwing-dev: 1 reported/);
  assert.doesNotMatch(ask("What models are on xwing-dev?", fixture, opts), /Qwen Local/);
  assert.doesNotMatch(ask("A xwingish host was mentioned", fixture, opts), /xwing: Tailscale presence/);
});

test("specific node without model membership does not become a zero-loading claim", () => {
  assert.match(ask("Is a model loaded on lenovo?", fixture, opts), /membership is unavailable/);
  assert.match(ask("Which models are on destroyer?", fixture, opts), /0 reported node model labels/);
  assert.match(ask("Which models are on destroyer?", fixture, opts), /not verified loaded instances/);
});

test("offline list names only explicitly offline machines and preserves unknowns", () => {
  const result = ask("List offline nodes", fixture, opts);
  assert.match(result, /4 nodes: 1 online, 1 offline, 2 unverified/);
  assert.match(result, /Reported offline: destroyer/);
  assert.doesNotMatch(result, /Reported offline: lenovo/);
  assert.match(ask("Which nodes are online?", fixture, opts), /Reported online: xwing/);
});

test("host-specific session or trace claims require independent node attribution", () => {
  const a = ask("Show Hermes sessions on xwing", fixture, opts);
  const b = ask("Any traces for destroyer?", fixture, opts);
  assert.match(a, /attribution is unverified/);
  assert.match(b, /attribution is unverified/);
  assert.doesNotMatch(a, /receipt-1/);
  assert.doesNotMatch(b, /test-trace/);
});

test("source unavailable and stale observations never return a named healthy node", () => {
  const unavailable = { ...fixture, nodes: { ...fixture.nodes, status: "unavailable" } };
  assert.match(ask("Are xwing models loaded?", unavailable, opts), /node inventory source is unavailable/);
  assert.match(ask("List online nodes", fixture), /No fresh authenticated fleet snapshot/);
});

test("unavailable nodes do not mask separately reported model, trace or session sources", () => {
  const partial = { ...fixture, nodes: { status: "unavailable", nodes: [] } };
  assert.match(ask("What fleet models are listed?", partial, opts), /catalog entries reported/);
  assert.match(ask("Show Hermes sessions across fleet", partial, opts), /launcher session receipts/);
  assert.match(ask("Show fleet traces", partial, opts), /trace-index entries/);
  assert.match(ask("Which fleet nodes are online?", partial, opts), /node inventory source is unavailable/);
});

test("invalid entries, oversized labels and unsafe requests fail closed", () => {
  const bad = {
    ...fixture,
    nodes: { status: "live", nodes: [null, undefined, 3, {}, {
      name: "xwing", tailscale_online: true, models: ["x".repeat(500)],
    }] },
  };
  const result = ask("What models are on xwing?", bad, opts);
  assert.ok(result.length <= 1800);
  assert.doesNotMatch(result, /x{200}/);
  assert.match(ask("ssh xwing and load models", fixture, opts), /cannot execute commands/);
  assert.match(ask("Run code on xwing", fixture, opts), /cannot execute commands/);
});
