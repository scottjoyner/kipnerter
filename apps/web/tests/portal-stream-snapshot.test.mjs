import test from "node:test";
import assert from "node:assert/strict";
import { readSanitizedControlPlaneSnapshot as snapshot } from "../lib/portal-stream-snapshot.mjs";
import { readBoundedPortalSection } from "../lib/portal-projection.mjs";
import { readFileSync } from "node:fs";

const origin = "http://127.0.0.1:13315";
const key = "synthetic-telemetry-only-token";
const source = {
  overview: { integrations: [{ id: "hermes", status: "healthy", local_status: "reported",
    raw_secrets: "CANARY_NEVER_LEAVE_PROCESS" }], readonly: true,
    observer_status: "reported", surprise_secret: "CANARY_NEVER_LEAVE_PROCESS" },
  models: { models: [{ id: "model-a", name: "model-a", source: "lmstudio_native_catalog", status: "catalog_available",
    private_prompt: "CANARY_NEVER_LEAVE_PROCESS" }], status: "reported" },
  nodes: { nodes: [{ name: "xwing", source: "tailscale", tailscale_online: true,
    models: ["Qwen"], secret_key: "CANARY_NEVER_LEAVE_PROCESS" }], status: "live" },
  traces: { traces: [{ correlation_id: "trace-1", outcome: "completed",
    raw_trace: "CANARY_NEVER_LEAVE_PROCESS" }], status: "historical" },
  sessions: { sessions: [{ id: "job-aaaaaaaaaaaa", agent: "hermes",
    status: "COMPLETED", input: "CANARY_NEVER_LEAVE_PROCESS" }], status: "reported" },
};

function mockFetch(rows = source) {
  const seen = [];
  const fetcher = async (url, opts) => {
    const name = url.pathname.split("/").at(-1);
    seen.push({ url: String(url), opts });
    if (!(name in rows)) throw new Error("source unavailable");
    return Response.json(rows[name]);
  };
  return { fetcher, seen };
}

test("SSE applies the same whitelist as polling across every source", async () => {
  const { fetcher, seen } = mockFetch();
  const out = await snapshot(key, origin, new AbortController().signal, fetcher);
  assert.deepEqual(Object.keys(out).sort(), Object.keys(source).sort());
  assert.doesNotMatch(JSON.stringify(out), /CANARY_NEVER_LEAVE_PROCESS/);
  for (const [name, raw] of Object.entries(source)) {
    assert.deepEqual(out[name], await readBoundedPortalSection(name, Response.json(raw)));
  }
  assert.equal(seen.length, 5);
  assert.deepEqual([...new Set(seen.map(s => s.url))].length, 5);
  for (const { url, opts } of seen) {
    assert.ok(url.startsWith(origin + "/api/v1/control-plane/"));
    assert.equal(opts.cache, "no-store");
    assert.equal(opts.method, "GET");
    assert.equal(opts.headers.Authorization, `Bearer ${key}`);
  }
});

test("malformed and unavailable source fail independently without blanking healthy nodes", async () => {
  const fetcher = async (url) => {
    const name = url.pathname.split("/").at(-1);
    if (name === "models") return Response.json({models:[]}, {status:503});
    if (name === "sessions") return Response.json({sessions:[{input:{leak:"CANARY"}}]});
    return Response.json(source[name]);
  };
  const out = await snapshot(key, origin, new AbortController().signal, fetcher);
  assert.deepEqual(out.models, { models: [], status: "unavailable" });
  assert.deepEqual(out.sessions, { sessions: [], status: "unavailable" });
  assert.equal(out.nodes.nodes[0].name, "xwing");
  assert.equal(out.traces.traces[0].correlation_id, "trace-1");
});

test("oversize content, invalid JSON and undeclared streamed bodies all fail closed", async () => {
  const fetcher = async (url) => {
    const name = url.pathname.split("/").at(-1);
    if (name === "nodes") return new Response("{}", {headers: {"content-length":"9999999"}});
    if (name === "models") {
      const stream = new ReadableStream({pull(controller) {
        controller.enqueue(new Uint8Array(8192).fill(65));
      }});
      return new Response(stream);
    }
    if (name === "traces") return new Response("{invalid", {status:200});
    return Response.json(source[name]);
  };
  const out = await snapshot(key, origin, new AbortController().signal, fetcher);
  assert.deepEqual(out.nodes, {nodes:[],status:"unavailable"});
  assert.deepEqual(out.models, {models:[],status:"unavailable"});
  assert.deepEqual(out.traces, {traces:[],status:"unavailable"});
  assert.equal(out.overview.readonly, true);
  assert.equal(out.sessions.sessions.length, 1);
});

test("aborted client must not query observer and returns all sources unavailable", async () => {
  const stop = new AbortController();
  stop.abort();
  const out = await snapshot(key, origin, stop.signal, () => {
    throw new Error("must not query observer after browser cancellation");
  });
  for (const [section, value] of Object.entries(out)) {
    assert.equal(value.status, "unavailable", section);
  }
});

test("the actual SSE route imports and uses the shared safe projector, not raw JSON", () => {
  const code = readFileSync(new URL("../app/api/portal/live/route.js", import.meta.url),"utf8");
  assert.match(code, /import \{ readSanitizedControlPlaneSnapshot \}/);
  assert.match(code, /JSON\.stringify\(await readSanitizedControlPlaneSnapshot\(/);
  assert.doesNotMatch(code, /await boundedJson\(/);
  assert.doesNotMatch(code, /await response\.json\(/);
});
