import NextAuth from "next-auth";
import { authOptions, authReady } from "../../../../lib/auth";

const handler = NextAuth(authOptions);

function denyUnconfiguredIdentity() {
  return Response.json(
    { error: "identity not configured" },
    { status: 503, headers: { "Cache-Control": "private, no-store" } },
  );
}

export async function GET(request, context) {
  if (!authReady) return denyUnconfiguredIdentity();
  return handler(request, context);
}

export async function POST(request, context) {
  if (!authReady) return denyUnconfiguredIdentity();
  return handler(request, context);
}
