import { getServerSession } from "next-auth";
import { authOptions, authReady, isAllowed } from "./auth";
import { readBoundedPortalSection } from "./portal-projection.mjs";
import { privateJson } from "./private-response.mjs";

const SECTIONS = new Set(["overview", "nodes", "models", "traces", "sessions"]);
export async function readPortal(section) {
  if (!SECTIONS.has(section)) return privateJson({ error: "not found" }, 404);
  if (!authReady) return privateJson({ error: "identity not configured" }, 503);
  const session = await getServerSession(authOptions);
  if (!isAllowed(session?.user?.email, session?.user?.id)) {
    return privateJson({ error: "authentication required" }, 401);
  }
  const token = process.env.KIPNERTER_GATEWAY_TOKEN;
  if (!token) return privateJson({ error: "gateway not configured" }, 503);
  const origin = process.env.KIPNERTER_INTERNAL_API_URL || "http://api:8000";
  try {
    const target = new URL(`/api/v1/control-plane/${section}`, origin);
    const reply = await fetch(target, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store", signal: AbortSignal.timeout(9000),
    });
    const data = await readBoundedPortalSection(section, reply);
    return privateJson(data);
  } catch {
    return privateJson({ error: "control plane unavailable" }, 502);
  }
}
