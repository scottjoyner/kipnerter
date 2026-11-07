import { getServerSession } from "next-auth";
import { authOptions, authReady, isAllowed } from "../../../../lib/auth.js";
import { DISPLAY_MODEL, discoverFleetNodes, endpointConfig } from "../../../../lib/lfm3-fleet.mjs";
import { resolveFleetNodeCredential } from "../../../../lib/lfm3-credentials.mjs";

// Private, read-only view of only explicitly admitted model candidates.
// No discovery of arbitrary Tailnet hosts and no model/token/IP disclosures.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store", Vary: "Cookie" };
let cache = null;
let cacheUntil = 0;
let pending = null;

export async function GET() {
  if (!authReady)
    return Response.json({ error: "Operator identity is not configured." }, { status: 503, headers });
  let session = null;
  try { session = await getServerSession(authOptions); } catch {}
  if (!isAllowed(session?.user?.email, session?.user?.id))
    return Response.json({ error: "Authorized operator session required." }, { status: 403, headers });

  let nodes;
  try { nodes = endpointConfig(process.env.KIPNERTER_LFM3_ENDPOINTS); }
  catch { return Response.json({ error: "Invalid private fleet configuration." }, { status: 503, headers }); }
  if (nodes.length === 0)
    return Response.json({ model: DISPLAY_MODEL, workers: [], note: "No LFM3 workers configured." }, { headers });
  if (Date.now() >= cacheUntil) {
    if (!pending) {
      pending = discoverFleetNodes(nodes, { resolveToken: resolveFleetNodeCredential })
        .then(workers => {
          cache = { model: DISPLAY_MODEL, workers,
            note: "Catalog-listed is not proof of generation. Served reflects this process only." };
          cacheUntil = Date.now() + 15000;
          return cache;
        })
        .finally(() => { pending = null; });
    }
    try { await pending; }
    catch { return Response.json({ error: "Fleet discovery is unavailable." }, { status: 503, headers }); }
  }
  return Response.json(cache, { headers });
}
