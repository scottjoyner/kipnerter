export const dynamic = "force-dynamic";

// Public, non-sensitive exact-build witness. A missing or invalid Docker build
// revision is unavailable; it must never be interpreted as a healthy rollout.
export async function GET() {
  const revision = process.env.KIPNERTER_RELEASE_SHA || "";
  if (!/^[a-f0-9]{40}$/.test(revision)) {
    return Response.json({ status: "unavailable" }, {
      status: 503, headers: { "Cache-Control": "no-store, max-age=0" },
    });
  }
  return Response.json({ source: "kipnerter-web", revision }, {
    headers: { "Cache-Control": "no-store, max-age=0" },
  });
}
