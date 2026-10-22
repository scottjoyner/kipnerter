import test from "node:test";
import assert from "node:assert/strict";
import { admittedIdentity, approvedTsidpProfile, parseAllowlist } from "../lib/identity.mjs";

const emails = parseAllowlist("Operator@Example.test,second@example.test");
const subjects = parseAllowlist("user:123,user:456");
test("signed tsidp subject and allowlisted email admit a real user with no email_verified field", () => {
  const p = { sub: "user:123", email: "operator@example.test" };
  assert.equal(approvedTsidpProfile(p, { email: p.email }, emails, subjects), true);
});
test("email-only attacker, mismatched signed email and unknown subject denied", () => {
  assert.equal(admittedIdentity("operator@example.test", "user:999", emails, subjects), false);
  assert.equal(admittedIdentity("attacker@example.test", "user:123", emails, subjects), false);
  assert.equal(approvedTsidpProfile({ sub: "user:123", email: "operator@example.test" },
    { email: "attacker@example.test" }, emails, subjects), false);
});
test("email_verified false is explicitly denied, omitted is supported", () => {
  assert.equal(approvedTsidpProfile({ sub: "user:123", email: "operator@example.test", email_verified: false },
    { email: "operator@example.test" }, emails, subjects), false);
  assert.equal(approvedTsidpProfile({ sub: "user:123", email: "operator@example.test" },
    { email: "operator@example.test" }, emails, subjects), true);
});
test("empty allowlists, wrong claim shapes, and newline controls deny", () => {
  for (const subject of ["", " user:123", "user:123\n", null, 2]) {
    assert.equal(admittedIdentity("operator@example.test", subject, emails, subjects), false);
  }
  for (const email of [null, 7, "operator@example.test\n", "notallowed@example.test"]) {
    assert.equal(admittedIdentity(email, "user:123", emails, subjects), false);
  }
  assert.equal(admittedIdentity("operator@example.test", "user:123", [], subjects), false);
  assert.equal(admittedIdentity("operator@example.test", "user:123", emails, []), false);
});
