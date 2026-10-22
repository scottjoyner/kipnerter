import test from "node:test";
import assert from "node:assert/strict";
import { projectControlPlaneSection, readBoundedPortalSection } from "../lib/portal-projection.mjs";

const fixtures = {
  overview: { integrations: [{ id: "assistx", status: "healthy", latency_ms: 30 }],
    source: "read-only observer", readonly: true, observer_status: "reported" },
  nodes: { nodes: [{ name: "xwing", source: "tailscale", models: ["Qwen"], inflight: 0,
    tailscale_online: true, last_seen: "" }], status: "live" },
  models: { models: [{ id: "a", name: "A", status: "catalog_available",
    source: "lmstudio_native_catalog", loaded_instances: 0, independently_verified: false }],
    status: "reported", observer_observed_at: { assistx: null, lmstudio: "2026-10-20T15:00:00Z" },
    fleet_runtime_nodes: [{ node: "xwing", ssh: "reported", model_binding: "unverified",
      native: { status: "reported", loaded_instances: 1, catalog_entries: 3 },
      openai: { status: "unavailable" },
      processes: { status: "reported", llama_server_count: 1, lmstudio_child_count: 0 } }] },
  traces: { status: "historical", traces: [{ correlation_id: "only-index",
    outcome: "completed", events: 1, last_ts_ms: 5, duration_ms: 20 }] },
  sessions: { status: "reported", sessions: [{ id: "job-abababababab",
    agent: "hermes", status: "COMPLETED", model_verified: false, archive_verified: true }] },
};

test("all five read-only sections preserve allowlisted browser-facing fields", async () => {
  for (const [section, fixture] of Object.entries(fixtures)) {
    const result = await readBoundedPortalSection(section, Response.json(fixture));
    assert.deepEqual(result, fixture, section);
  }
});

test("unknown upstream keys and nested private prompt fields cannot reach browser", () => {
  const doc = structuredClone(fixtures.nodes);
  doc.private_key = "never-forward-this-value";
  doc.nodes[0].raw_prompt = "never-forward-this-value";
  const result = projectControlPlaneSection("nodes", doc);
  assert.doesNotMatch(JSON.stringify(result), /never-forward/);

  const modelDoc = structuredClone(fixtures.models);
  modelDoc.fleet_runtime_nodes[0].native.raw_payload = "never-forward-this-value";
  modelDoc.observer_observed_at.internal_key = "never-forward-this-value";
  assert.doesNotMatch(JSON.stringify(projectControlPlaneSection("models", modelDoc)), /never-forward/);
});

test("missing arrays, oversized rows, malformed nested structures and write claims deny", () => {
  assert.throws(() => projectControlPlaneSection("evil", fixtures.nodes), /unsupported/);
  assert.throws(() => projectControlPlaneSection("nodes", {status:"live"}), /invalid control-plane/);
  assert.throws(() => projectControlPlaneSection("nodes",
    {nodes: Array(101).fill({name:"x"})}), /invalid control-plane/);
  assert.throws(() => projectControlPlaneSection("overview",
    {integrations:[],readonly:false}), /not a read-only/);
  assert.throws(() => projectControlPlaneSection("nodes",
    {nodes:[{name:"x",source:"tailscale",models:Array(13).fill("a")}]}), /unbounded node labels/);
  assert.throws(() => projectControlPlaneSection("traces",
    {traces:[{correlation_id:"x",outcome:["injected"]}]}), /malformed telemetry row/);
  assert.throws(() => projectControlPlaneSection("models",
    {...fixtures.models,fleet_runtime_nodes:Array(7).fill({})}), /unbounded fleet witnesses/);
});

test("non-2xx, declared oversize and streamed oversize reject before forwarding data", async () => {
  await assert.rejects(readBoundedPortalSection("nodes",
    Response.json({nodes:[]},{status:401})), /upstream unavailable/);
  await assert.rejects(readBoundedPortalSection("nodes",new Response("{}",
    {headers:{"content-length":"999999"}})), /declared telemetry size/);
  let pulled = 0;
  const stream = new ReadableStream({pull(controller) {
    pulled++;
    controller.enqueue(new Uint8Array(8192).fill(32));
  }});
  await assert.rejects(readBoundedPortalSection("nodes",new Response(stream)),
    /streamed telemetry exceeds cap/);
  assert.ok(pulled < 40);
});

test("malformed rows, untrusted arrays and overlong response strings fail closed", () => {
  assert.throws(() => projectControlPlaneSection("sessions",
    {sessions:[null]}), /malformed telemetry row/);
  assert.throws(() => projectControlPlaneSection("sessions",
    {sessions:[{agent:"a".repeat(600)}]}), /malformed telemetry row/);
  assert.throws(() => projectControlPlaneSection("models",
    {...fixtures.models,observer_observed_at:["bad"]}), /invalid model observer/);
});
