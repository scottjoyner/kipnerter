/**
 * SensorGraft browser storage adapter. IndexedDB is origin-scoped: nothing is
 * uploaded, synced or readable by the server. User may export/delete at will.
 */
const NAME = "kipnerter-sensorgraft-v1";
const STORE = "traces";
const LIMIT = 250;
export const TRACE_FORMAT = "sensorgraft.browser.trace.v1";

function db() {
  if (typeof indexedDB === "undefined") throw new Error("IndexedDB unavailable");
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function transaction(mode, action) {
  const conn = await db();
  try {
    return await new Promise((resolve, reject) => {
      const tx = conn.transaction(STORE, mode);
      const store = tx.objectStore(STORE);
      let result;
      const request = action(store);
      request.onsuccess = () => { result = request.result; };
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || Error("Trace transaction aborted"));
    });
  } finally {
    conn.close();
  }
}
export async function listTraces() {
  const values = await transaction("readonly", store => store.getAll());
  return values.sort((a,b) => a.id - b.id).slice(-LIMIT);
}
export async function rememberTrace(trace) {
  const clean = {
    schema: TRACE_FORMAT,
    created_at: new Date().toISOString(),
    model: "LiquidAI/LFM3-1.7B-ONNX",
    harness: "browser-v0.1.0",
    prompt: String(trace.prompt || "").slice(0, 4000),
    response: String(trace.response || "").slice(0, 6000),
    elapsed_ms: Math.min(3_600_000, Math.max(0, Number(trace.elapsed_ms) || 0)),
    memory_hits: Math.min(8, Math.max(0, Number(trace.memory_hits) || 0)),
    feedback: null,
    federated: false,
  };
  const id = await transaction("readwrite", store => store.add(clean));
  // Bound local retention; user controls deletion and export.
  const records = await transaction("readonly", store => store.getAllKeys());
  if (records.length > LIMIT) {
    // IndexedDB keys are monotonically increasing; evict oldest first.
    for (const oldId of records.slice(0, records.length - LIMIT)) {
      await transaction("readwrite", store => store.delete(oldId));
    }
  }
  return id;
}
export async function updateFeedback(id, feedback) {
  if (!Number.isSafeInteger(id) || !["useful", "not-useful"].includes(feedback)) return;
  await transaction("readwrite", store => {
    const request = store.get(id);
    request.onsuccess = () => {
      if (request.result) { const trace = request.result; trace.feedback = feedback; store.put(trace); }
    };
    return request;
  });
}
export async function clearTraces() {
  await transaction("readwrite", store => store.clear());
}
export async function exportTraces() {
  const traces = await listTraces();
  return JSON.stringify({ schema: TRACE_FORMAT, exported_at: new Date().toISOString(), traces }, null, 2);
}
