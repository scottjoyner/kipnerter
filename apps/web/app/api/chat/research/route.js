import { resolveFleetNodeCredential } from "../../../../lib/lfm3-credentials.mjs";
import { getServerSession } from "next-auth";
import { authOptions, authReady, isAllowed } from "../../../../lib/auth.js";
import { boundedJson } from "../../../../lib/stream-utils.mjs";
import { endpointConfig } from "../../../../lib/lfm3-fleet.mjs";
import { runParallelLFM3Research } from "../../../../lib/lfm3-parallel.mjs";

// Private operator-only model research. No tools, commands, SensorGraft reads,
// database access, or browser-supplied fleet routing. The public chat route
// never imports this handler.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const activePrincipals = new Set();
const recentByPrincipal = new Map();
let activeRequests = 0;
const commonHeaders = { "Cache-Control": "private, no-store", Vary: "Cookie, Origin" };

export function validateResearchInput(body) {
  if (!body || typeof body !== "object" || Array.isArray(body) ||
      Object.keys(body).some(key => key !== "question") ||
      typeof body.question !== "string") throw new Error("invalid research request");
  const question = body.question.trim();
  if (question.length < 4 || question.length > 700) throw new Error("invalid research question");
  return question;
}

function claimPrincipal(principal) {
  const now = Date.now();
  const previous = recentByPrincipal.get(principal) || [];
  const recent = previous.filter(ts => ts > now - 60000);
  // Process-local defense in depth; edge/global controls are still required.
  if (recent.length >= 3 || activeRequests >= 2 || activePrincipals.has(principal)) {
    recentByPrincipal.set(principal, recent);
    return false;
  }
  if (recentByPrincipal.size > 256) recentByPrincipal.clear();
  recentByPrincipal.set(principal, [...recent, now]);
  activePrincipals.add(principal);
  activeRequests += 1;
  return true;
}
function releasePrincipal(principal) {
  activePrincipals.delete(principal);
  activeRequests = Math.max(0, activeRequests - 1);
}

export async function POST(request) {
  // Strict same-origin check protects this cookie-backed operator endpoint.
  const expected = new URL(process.env.NEXTAUTH_URL || "https://kipnerter.com").origin;
  if (request.headers.get("origin") !== expected)
    return Response.json({ error: "Same-origin private session required." },
      { status: 403, headers: commonHeaders });
  if (!authReady)
    return Response.json({ error: "Private identity provider unavailable." },
      { status: 503, headers: commonHeaders });
  let session;
  try { session = await getServerSession(authOptions); } catch { session = null; }
  if (!isAllowed(session?.user?.email, session?.user?.id))
    return Response.json({ error: "Authorized operator session required." },
      { status: 403, headers: commonHeaders });

  let question;
  try {
    const body = await boundedJson(new Response(request.body, { headers: request.headers }), 6000);
    question = validateResearchInput(body);
  } catch (error) {
    const oversized = /exceeds cap/.test(error?.message || "");
    return Response.json({ error: oversized ? "Request too large." : "Invalid research question." },
      { status: oversized ? 413 : 400, headers: commonHeaders });
  }
  const principal = session.user.id || session.user.email;
  if (!claimPrincipal(principal))
    return Response.json({ error: "Parallel research is busy. Please retry later." },
      { status: 429, headers: commonHeaders });

  try {
    let nodes;
    try { nodes = endpointConfig(process.env.KIPNERTER_LFM3_ENDPOINTS); }
    catch { return Response.json({ error: "LFM3 fleet configuration invalid." }, { status: 503, headers: commonHeaders }); }
    const result = await runParallelLFM3Research({
      authorized: true,
      question,
      subtasks: [
        "Produce a concise, evidence-aware answer and explain the main reasoning.",
        "Independently examine assumptions, uncertainty, failure modes, and alternatives.",
      ],
      nodes,
      resolveToken: resolveFleetNodeCredential,
      signal: request.signal,
    });
    return Response.json(result.status === 200 ? result : { error: result.error },
      { status: result.status === 499 ? 408 : result.status, headers: commonHeaders });
  } finally {
    releasePrincipal(principal);
  }
}
