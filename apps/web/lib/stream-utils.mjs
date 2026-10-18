// Shared safe bounded reader for authenticated telemetry. Do not call text()
// on an untrusted chunked response: it can buffer an unlimited payload before
// a post-hoc string-length check. This enforces the limit *during* reading.
export const MAX_TELEMETRY_BYTES = 128000;

export async function boundedJson(response, maxBytes = MAX_TELEMETRY_BYTES) {
  if (!response.ok) throw new Error("upstream unavailable");
  const declared = response.headers.get("content-length");
  if (declared !== null && (!/^\d+$/.test(declared) ||
      Number(declared) > maxBytes)) {
    throw new Error("declared telemetry size exceeds cap");
  }
  if (!response.body) throw new Error("empty upstream response");
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) throw new Error("streamed telemetry exceeds cap");
      chunks.push(value);
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }
  const buffer = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    buffer.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(buffer));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("invalid telemetry document");
  }
  return parsed;
}

// Return immediately when a client disconnects rather than preserving a
// sleeping SSE loop for 15 more seconds after closing its stream.
export function abortableDelay(ms, signal) {
  if (signal.aborted) return Promise.resolve(false);
  return new Promise(resolve => {
    let timer;
    function finish(continued) {
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      resolve(continued);
    }
    function onAbort() { finish(false); }
    signal.addEventListener("abort", onAbort, { once: true });
    timer = setTimeout(() => finish(true), ms);
  });
}
