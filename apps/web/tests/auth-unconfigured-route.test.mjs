import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../app/api/auth/[...nextauth]/route.js", import.meta.url), "utf8");

test("OIDC provider route denies before NextAuth when identity is unconfigured", () => {
  assert.match(source, /import \{ authOptions, authReady \} from/);
  assert.match(source, /export async function GET\(request, context\) \{\s*if \(!authReady\) return denyUnconfiguredIdentity\(\)/);
  assert.match(source, /export async function POST\(request, context\) \{\s*if \(!authReady\) return denyUnconfiguredIdentity\(\)/);
  assert.match(source, /status: 503/);
  assert.match(source, /Cache-Control.*private, no-store/);
  assert.doesNotMatch(source, /export \{ handler as GET, handler as POST \}/);
});
