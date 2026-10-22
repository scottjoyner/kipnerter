import test from "node:test";
import assert from "node:assert/strict";
import { validatedTsidpIssuer, validIdentityList, isTsidpRuntimeReady } from "../lib/tsidp-config.mjs";

const good = () => ({
  issuer: "https://idp.tailcb8954.ts.net",
  clientId: "registered-oidc-client",
  clientSecret: "synthetic-client-secret-with-length",
  secret: "synthetic-test-jwt-secret-not-production",
  allowedEmails: "operator@example.test",
  allowedSubjects: "signed-user:123",
  environment: "staging",
  callbackOrigin: "https://staging.kipnerter.com",
});

test("valid root issuer and signed two-claim allowlist gates admission candidate", () => {
  assert.equal(validatedTsidpIssuer(good().issuer), good().issuer);
  assert.equal(isTsidpRuntimeReady(good()), true);
  assert.equal(isTsidpRuntimeReady({ ...good(), environment: "production",
    callbackOrigin: "https://kipnerter.com" }), true);
  assert.equal(isTsidpRuntimeReady({ ...good(), environment: "tailnet-preview",
    callbackOrigin: "https://x1-370.tailcb8954.ts.net:8449" }), true);
});

test("runtime rejects non-Tailscale, credentialed, redirected or pathful issuers", () => {
  const bad = [
    "", "http://idp.tailcb8954.ts.net",
    "https://idp.tailcb8954.ts.net.evil.example",
    "https://evil.example",
    "https://user:password@idp.tailcb8954.ts.net",
    "https://idp.tailcb8954.ts.net/.well-known/openid-configuration",
    "https://idp.tailcb8954.ts.net/path",
    "https://idp.tailcb8954.ts.net?to=evil",
    "https://idp.tailcb8954.ts.net#fragment",
    "https://idp.tailcb8954.ts.net:8443",
    "https://localhost", "https://foo.localhost",
    "https://.ts.net", "https://idp..ts.net",
  ];
  for (const issuer of bad) {
    assert.equal(validatedTsidpIssuer(issuer), null, issuer);
    assert.equal(isTsidpRuntimeReady({ ...good(), issuer }), false, issuer);
  }
});

test("runtime refuses absent or malformed email and subject allowlists", () => {
  const invalid = [
    ["allowedEmails", ""], ["allowedEmails", "operator@example.test, operator2@example.test"],
    ["allowedEmails", "Operator@Example.test"],
    ["allowedEmails", "operator@example.test,operator@example.test"],
    ["allowedEmails", "operator@example.test\n"],
    ["allowedSubjects", ""], ["allowedSubjects", "s"],
    ["allowedSubjects", "subject-one, subject-two"],
    ["allowedSubjects", "signed-user:123,signed-user:123"],
    ["allowedSubjects", "signed-user:123\n"],
  ];
  for (const [key, value] of invalid) {
    assert.equal(isTsidpRuntimeReady({ ...good(), [key]: value }), false, `${key}=${value}`);
  }
  assert.equal(validIdentityList("operator@example.test", "email"), true);
  assert.equal(validIdentityList("signed-user:123", "subject"), true);
  assert.equal(validIdentityList("signed-user:123", "unknown"), false);
});

test("runtime refuses invalid client credentials, callback and environment", () => {
  for (const [key, value] of [
    ["clientId", ""], ["clientId", "malicious\nclient"],
    ["clientSecret", "short"], ["clientSecret", "untrusted\n" + "s".repeat(24)],
    ["secret", "too-short"], ["secret", "untrusted\r" + "s".repeat(33)],
    ["callbackOrigin", "https://kipnerter.com"],
    ["callbackOrigin", "http://staging.kipnerter.com"],
    ["environment", "unknown"],
    ["environment", "preview"],
    ["callbackOrigin", "https://x1-370.tailcb8954.ts.net:8449"],
  ]) assert.equal(isTsidpRuntimeReady({ ...good(), [key]: value }), false, key);
});

test("unconfigured identity remains off even when client identifier is set", () => {
  const cfg = good();
  cfg.issuer = "";
  assert.equal(isTsidpRuntimeReady(cfg), false);
});
