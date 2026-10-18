import { getServerSession } from "next-auth";
import { authOptions, authReady, isAllowed } from "../../../../lib/auth";
import { boundedJson, abortableDelay } from "../../../../lib/stream-utils.mjs";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const SECTIONS = ["overview", "models", "nodes", "traces", "sessions"];
const EMPTY = {
  overview: { integrations: [], status: "unavailable" },
  models: { models: [], status: "unavailable" },
  nodes: { nodes: [], status: "unavailable" },
  traces: { traces: [], status: "unavailable" },
  sessions: { sessions: [], status: "unavailable" },
};
const MAX_STREAMS = 8;
const POLL_MS = 15000;
const LIFETIME_MS = 120000;
let openStreams = 0;

// Poll sanitized read-only API projections; never relay arbitrary upstream events.
async function snapshot(token, origin, stopSignal) {
  const result = await Promise.all(SECTIONS.map(async (section) => {
    try {
      const url = new URL(`/api/v1/control-plane/${section}`, origin);
      const response = await fetch(url, {
        headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.any([stopSignal, AbortSignal.timeout(7000)]),
      });
      return [section, await boundedJson(response)];
    } catch {
      return [section, EMPTY[section]];
    }
  }));
  return Object.fromEntries(result);
}

export async function GET(request) {
  if (!authReady) return Response.json({ error: "identity not configured" }, { status: 503 });
  const session = await getServerSession(authOptions);
  if (!isAllowed(session?.user?.email, session?.user?.id)) {
    return Response.json({ error: "authentication required" }, { status: 401 });
  }
  const token = process.env.KIPNERTER_GATEWAY_TOKEN;
  if (!token) return Response.json({ error: "gateway not configured" }, { status: 503 });
  if (openStreams >= MAX_STREAMS) {
    return Response.json({ error: "stream capacity reached" }, {
      status: 429, headers: { "Retry-After": "15" },
    });
  }
  // The private container DNS name is never returned to the browser.
  const origin = process.env.KIPNERTER_INTERNAL_API_URL || "http://api:8000";
  ++openStreams;
  const encoder = new TextEncoder();
  let stopped = false;
  const abort = new AbortController();
  let closeStream = () => {};
  const stream = new ReadableStream({
    start(controller) {
      let last = "";
      const deadline = Date.now() + LIFETIME_MS;
      const expiry = setTimeout(() => closeStream(), LIFETIME_MS);
      closeStream = () => {
        if (stopped) return;
        stopped = true;
        clearTimeout(expiry);
        abort.abort();
        request.signal.removeEventListener("abort", closeStream);
        openStreams = Math.max(0, openStreams - 1);
        try { controller.close(); } catch { /* client disconnected */ }
      };
      request.signal.addEventListener("abort", closeStream, { once: true });
      (async () => {
        controller.enqueue(encoder.encode("retry: 15000\n: authenticated read-only stream\n\n"));
        while (!stopped && Date.now() < deadline) {
          const value = JSON.stringify(await snapshot(token, origin, abort.signal));
          if (stopped) break;
          // Abort rather than retain unlimited queued snapshots for a stalled
          // browser connection. The browser may reconnect under the same auth.
          if (controller.desiredSize !== null && controller.desiredSize <= 0) break;
          if (value !== last) {
            controller.enqueue(encoder.encode(`event: snapshot\ndata: ${value}\n\n`));
            last = value;
          } else {
            controller.enqueue(encoder.encode(": heartbeat\n\n"));
          }
          if (!await abortableDelay(POLL_MS, abort.signal)) break;
        }
      })().catch(() => {}).finally(closeStream);
    },
    cancel() { closeStream(); },
  });
  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "private, no-store, no-transform",
      "X-Accel-Buffering": "no",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
