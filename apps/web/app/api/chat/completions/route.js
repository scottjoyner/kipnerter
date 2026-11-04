import { completeFleetChat, endpointConfig } from "../../../../lib/lfm3-fleet.mjs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const perClient = new Map();
function allowed(request) {
  // Defense in depth only. Enforce canonical IP rate limits and bot protection at Caddy.
  const client = (request.headers.get("x-real-ip") || request.headers.get("x-forwarded-for") || "unknown").split(",")[0].trim().slice(0, 90);
  if (perClient.size > 5000) perClient.clear();
  const now = Date.now();
  const current = perClient.get(client);
  const entry = current && current.until > now ? current : { count: 0, until: now + 60000 };
  entry.count++;
  perClient.set(client, entry);
  return entry.count <= 8;
}
const noStore = { "Cache-Control": "no-store" };
export async function POST(request) {
  if (!allowed(request)) return Response.json({ error: "Too many messages. Try again shortly." }, { status: 429, headers: noStore });
  if (Number(request.headers.get("content-length") || 0) > 48000) {
    return Response.json({ error: "Request too large." }, { status: 413, headers: noStore });
  }
  let body;
  try {
    const raw = await request.text();
    if (raw.length > 48000) return Response.json({ error: "Request too large." }, { status: 413, headers: noStore });
    body = JSON.parse(raw);
    if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).some(k => k !== "messages")) throw new Error("unexpected fields");
  } catch {
    return Response.json({ error: "Invalid chat request." }, { status: 400, headers: noStore });
  }
  let nodes;
  try { nodes = endpointConfig(process.env.KIPNERTER_LFM3_ENDPOINTS); }
  catch { return Response.json({ error: "LFM3 fleet configuration is invalid." }, { status: 503, headers: noStore }); }
  try {
    const result = await completeFleetChat(body.messages, {
      nodes, token: process.env.KIPNERTER_LFM3_BEARER || "", signal: request.signal,
    });
    return Response.json(result.status === 200 ? result : { error: result.error },
      { status: result.status === 499 ? 408 : result.status, headers: noStore });
  } catch {
    return Response.json({ error: "Invalid conversation. Messages must be short, user/assistant text only." },
      { status: 400, headers: noStore });
  }
}
