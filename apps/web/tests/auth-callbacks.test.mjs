import test from "node:test";
import assert from "node:assert/strict";

process.env.TSIDP_ISSUER = "https://idp.synthetic-tailnet.ts.net";
process.env.TSIDP_CLIENT_ID = "synthetic-client-id";
process.env.TSIDP_CLIENT_SECRET = "synthetic-client-secret";
process.env.NEXTAUTH_SECRET = "x".repeat(48);
process.env.NEXTAUTH_URL = "https://kipnerter.com";
process.env.KIPNERTER_ALLOWED_EMAILS = "test.operator@example.test";
process.env.KIPNERTER_ALLOWED_TSIDP_SUBJECTS = "stable-subject-7";
const { authOptions, authReady, isAllowed } = await import("../lib/auth.js");

test("issuer config and signed identity must both be allowlisted", () => {
  assert.equal(authReady, true);
  assert.equal(isAllowed("test.operator@example.test", "stable-subject-7"), true);
  assert.equal(isAllowed("test.operator@example.test", "different-subject"), false);
});
test("actual NextAuth signIn callback accepts signed whois email without absent email_verified", async () => {
  const signed = { sub: "stable-subject-7", email: "test.operator@example.test" };
  assert.equal(await authOptions.callbacks.signIn({
    profile: signed, user: { email: signed.email },
  }), true);
  assert.equal(await authOptions.callbacks.signIn({
    profile: { ...signed, email_verified: false }, user: { email: signed.email },
  }), false);
});
test("NextAuth session callback excludes wrong subject and injects verified subject id", async () => {
  const session = { user: { email: "test.operator@example.test" } };
  assert.equal(await authOptions.callbacks.session({ session, token: { sub: "wrong" } }), null);
  const admitted = await authOptions.callbacks.session({
    session, token: { sub: "stable-subject-7" },
  });
  assert.equal(admitted.user.id, "stable-subject-7");
  assert.equal(authOptions.session.maxAge, 900);
});
