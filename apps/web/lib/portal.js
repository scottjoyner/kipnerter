import { getServerSession } from "next-auth";
import { authOptions, authReady, isAllowed } from "./auth";
import { readBoundedPortalSection } from "./portal-projection.mjs";

const SECTIONS = new Set(["overview", "nodes", "models", "traces", "sessions"]);
export async function readPortal(section) {
  if (!SECTIONS.has(section)) return Response.json({ error: "not found" }, { status: 404 });
  if (!authReady) return Response.json({ error: "identity not configured" }, { status: 503 });
  const session = await getServerSession(authOptions);
  if (!isAllowed(session?.user?.email, session?.user?.id)) {
    return Response.json({ error: "authentication required" }, { status: 401 });
  }
  const token = process.env.KIPNERTER_GATEWAY_TOKEN;
  if (!token) return Response.json({ error: "gateway not configured" }, { status: 503 });
  const origin = process.env.KIPNERTER_INTERNAL_API_URL || "http://api:8000";
  try {
    const target = new URL(`/api/v1/control-plane/${section}`, origin);
    const reply = await fetch(target, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store", signal: AbortSignal.timeout(9000),
    });
    const data = await readBoundedPortalSection(section, reply);
    return Response.json(data, { headers: { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" } });
  } catch {
    return Response.json({ error: "control plane unavailable" }, { status: 502 });
  }
}
