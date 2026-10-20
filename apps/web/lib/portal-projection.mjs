/** Bounded, allowlisted projection for authenticated polling of private API.
 * The same 128 KB streaming cap is used by authenticated SSE. Never forward
 * an arbitrary upstream JSON object to the browser.
 */
import { boundedJson } from "./stream-utils.mjs";

const SECTION = Object.freeze({
  overview: { key: "integrations", limit: 12,
    top: ["source", "observer_status", "observer_observed_at", "readonly"],
    row: ["id", "status", "gateway_status", "local_status", "source", "latency_ms"] },
  nodes: { key: "nodes", limit: 100,
    top: ["status", "tailscale_status", "assistx_status", "assistx_observed_at", "observer_observed_at"],
    row: ["name", "source", "models", "last_seen", "inflight", "tailscale_online"] },
  models: { key: "models", limit: 100,
    top: ["status", "source", "assistx_status", "runtime_status", "observer_observed_at",
          "fleet_runtime_status", "fleet_runtime_observed_at", "fleet_runtime_nodes"],
    row: ["id", "name", "nodes", "source", "status", "loaded_instances", "independently_verified"] },
  traces: { key: "traces", limit: 25,
    top: ["status", "source", "observer_observed_at", "last_event_at"],
    row: ["correlation_id", "outcome", "events", "last_ts_ms", "duration_ms"] },
  sessions: { key: "sessions", limit: 50,
    top: ["status", "source", "observer_observed_at"],
    row: ["id", "agent", "status", "model", "created_utc", "ended_utc",
          "model_verified", "archive_verified", "harvest_hold"] },
});

const REQUIRED = Object.freeze({
  overview: ["id", "status"],
  nodes: ["name", "source"],
  models: ["id", "name", "source", "status"],
  traces: ["correlation_id", "outcome"],
  sessions: ["id", "agent", "status"],
});
const isRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);
const primitive = value => value === null || typeof value === "boolean" ||
  (typeof value === "string" && value.length <= 512) ||
  (typeof value === "number" && Number.isFinite(value) && Math.abs(value) < 1e15);
function scalar(value) {
  if (!primitive(value)) throw new TypeError("invalid projected telemetry value");
  return value;
}
function pick(row, keys) {
  if (!isRecord(row)) throw new TypeError("unexpected telemetry row");
  return Object.fromEntries(keys.filter(key => Object.hasOwn(row, key))
    .map(key => [key, scalar(row[key])]));
}
function boundedNames(value, limit) {
  if (!Array.isArray(value) || value.length > limit) throw new TypeError("unbounded node labels");
  return value.map(item => {
    if (typeof item !== "string" || item.length > 160) throw new TypeError("invalid node label");
    return item;
  });
}
function runtimeEntry(entry, keys) {
  return pick(entry, keys);
}
function runtimeNode(row) {
  const output = pick(row, ["node", "ssh", "model_binding"]);
  output.native = runtimeEntry(row.native, ["status", "catalog_entries", "loaded_instances"]);
  output.openai = runtimeEntry(row.openai, ["status", "advertised_entries"]);
  output.processes = runtimeEntry(row.processes, ["status", "llama_server_count", "lmstudio_child_count"]);
  return output;
}
export function projectControlPlaneSection(section, document) {
  const spec = Object.hasOwn(SECTION, section) ? SECTION[section] : null;
  if (!spec || !isRecord(document)) throw new TypeError("unsupported control-plane section");
  const rows = document[spec.key];
  if (!Array.isArray(rows) || rows.length > spec.limit) {
    throw new TypeError("invalid control-plane rows");
  }
  const out = {};
  for (const field of spec.top) {
    if (!Object.hasOwn(document, field)) continue;
    if (section === "models" && field === "observer_observed_at") {
      const obs = document[field];
      if (!isRecord(obs)) throw new TypeError("invalid model observer reading");
      out[field] = pick(obs, ["assistx", "lmstudio"]);
    } else if (section === "models" && field === "fleet_runtime_nodes") {
      const runtime = document[field];
      if (!Array.isArray(runtime) || runtime.length > 6) throw new TypeError("unbounded fleet witnesses");
      out[field] = runtime.map(runtimeNode);
    } else {
      out[field] = scalar(document[field]);
    }
  }
  out[spec.key] = rows.map(row => {
    if (!isRecord(row) || REQUIRED[section].some(key =>
      typeof row[key] !== "string" || !row[key] || row[key].length > 160
    )) throw new TypeError("malformed telemetry row");
    const projected = {};
    for (const field of spec.row) {
      if (!Object.hasOwn(row ?? {}, field)) continue;
      projected[field] = section === "nodes" && field === "models"
        ? boundedNames(row[field], 12) : scalar(row[field]);
    }
    if (!isRecord(row)) throw new TypeError("malformed telemetry row");
    return projected;
  });
  if (section === "overview" && out.readonly !== true) {
    throw new TypeError("not a read-only projection");
  }
  return out;
}
export async function readBoundedPortalSection(section, response) {
  return projectControlPlaneSection(section, await boundedJson(response));
}
