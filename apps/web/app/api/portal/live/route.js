import { getServerSession } from "next-auth";
import { authOptions, authReady, isAllowed } from "../../../../lib/auth";

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
async function snapshot(token, origin) {
  const result = await Promise.all(SECTIONS.map(async (section) => {
    try {
      const url = new URL(`/api/v1/control-plane/${section}`, origin);
      const response = await fetch(url, {
        headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(7000),
      });
      if (!response.ok) return [section, EMPTY[section]];
      const size = Number(response.headers.get("content-length") || "0");
      if (size > 128000) return [section, EMPTY[section]];
      const text = await response.text();
      if (text.length > 128000) return [section, EMPTY[section]];
      const parsed = JSON.parse(text);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return [section, EMPTY[section]];
      }
      return [section, parsed];
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
  let closeStream = () => {};
  const stream = new ReadableStream({
    start(controller) {
      let last = "";
      const deadline = Date.now() + LIFETIME_MS;
      closeStream = () => {
        if (stopped) return;
        stopped = true;
        openStreams = Math.max(0, openStreams - 1);
        try { controller.close(); } catch { /* client disconnected */ }
      };
      request.signal.addEventListener("abort", closeStream, { once: true });
      (async () => {
        controller.enqueue(encoder.encode("retry: 15000\n: authenticated read-only stream\n\n"));
        while (!stopped && !request.signal.aborted && Date.now() < deadline) {
          const value = JSON.stringify(await snapshot(token, origin));
          if (value !== last && !stopped) {
            controller.enqueue(encoder.encode(`event: snapshot\ndata: ${value}\n\n`));
            last = value;
          } else if (!stopped) {
            controller.enqueue(encoder.encode(": heartbeat\n\n"));
          }
          await new Promise(resolve => setTimeout(resolve, POLL_MS));
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
