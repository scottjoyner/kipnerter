import { NextResponse } from "next/server";
import { currentSession, allowedUser, operatorUser, identityReady } from "../../../../lib/auth";

export const dynamic = "force-dynamic";
const resources = {
  status: "/api/v1/console/status",
  models: "/api/v1/gateway/lmstudio/v1/models",
  nodes: "/api/v1/console/nodes"
};
const noStore = { "Cache-Control": "private, no-store, max-age=0" };
const error = (code, reason) => NextResponse.json({ error: reason }, { status: code, headers: noStore });

async function access(resource) {
  if (!identityReady) return { error: error(503, "Identity is not configured") };
  const session = await currentSession();
  if (!allowedUser(session)) return { error: error(401, "Unauthorized") };
  if ((resource === "traces" || resource === "nodes") && !operatorUser(session))
    return { error: error(403, "Operator role required") };
  if (!process.env.KIPNERTER_GATEWAY_TOKEN || !process.env.KIPNERTER_API_INTERNAL_URL)
    return { error: error(503, "Internal gateway is not configured") };
  return { token: process.env.KIPNERTER_GATEWAY_TOKEN };
}

async function upstream(path, token, options = {}) {
  const base = process.env.KIPNERTER_API_INTERNAL_URL.replace(/\/$/, "");
  try {
    const response = await fetch(base + path, {
      method: options.method || "GET",
      headers: { "Authorization": `Bearer ${token}`, "Accept": "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
      body: options.body,
      cache: "no-store",
      signal: AbortSignal.timeout(30000)
    });
    const raw = await response.text();
    if (raw.length > 1024 * 1024) return error(502, "Upstream response too large");
    let payload;
    try { payload = JSON.parse(raw); }
    catch { return error(502, "Invalid upstream response"); }
    return NextResponse.json(payload, { status: response.status, headers: noStore });
  } catch {
    return error(502, "Fleet gateway unavailable");
  }
}

export async function GET(request, context) {
  const { resource } = await context.params;
  if (!(resource in resources) && resource !== "traces") return error(404, "Resource not found");
  const auth = await access(resource);
  if (auth.error) return auth.error;
  if (resource === "traces") {
    const trace = new URL(request.url).searchParams.get("id") || "";
    if (!/^[a-zA-Z0-9_-]{8,96}$/.test(trace)) return error(400, "Invalid trace identifier");
    return upstream(`/api/v1/console/traces/${encodeURIComponent(trace)}`, auth.token);
  }
  return upstream(resources[resource], auth.token);
}

export async function POST(request, context) {
  const { resource } = await context.params;
  if (resource !== "chat") return error(404, "Resource not found");
  const auth = await access(resource);
  if (auth.error) return auth.error;
  if (process.env.KIPNERTER_WEB_CHAT_ENABLED !== "true") return error(503, "Chat dispatch is disabled");
  if (request.headers.get("origin") !== new URL(request.url).origin) return error(403, "Invalid request origin");
  if (Number(request.headers.get("content-length") || 0) > 32000)
    return error(413, "Request too large");
  let payload;
  try { payload = await request.json(); }
  catch { return error(400, "Invalid JSON"); }
  const model = payload?.model;
  const messages = payload?.messages;
  if (typeof model !== "string" || !/^[a-zA-Z0-9._:/+-]{1,160}$/.test(model) ||
      !Array.isArray(messages) || !messages.length || messages.length > 24 ||
      messages.some(m => !["user", "assistant"].includes(m?.role) ||
        typeof m?.content !== "string" || m.content.length > 6000))
    return error(400, "Invalid chat request");
  return upstream("/api/v1/gateway/lmstudio/v1/chat/completions", auth.token, {
    method: "POST",
    body: JSON.stringify({ model, messages, stream: false, max_tokens: 1024 })
  });
}
