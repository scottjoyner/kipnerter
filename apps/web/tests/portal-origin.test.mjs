import test from "node:test";
import assert from "node:assert/strict";
import { expectedAuthOrigin, isConfiguredOrigin } from "../lib/portal-origin.mjs";

test("production and staging have distinct exact callback origins", () => {
  assert.equal(expectedAuthOrigin("production"), "https://kipnerter.com");
  assert.equal(expectedAuthOrigin("staging"), "https://staging.kipnerter.com");
  assert.equal(expectedAuthOrigin("preview"), null);
  assert.equal(isConfiguredOrigin("production", "https://kipnerter.com"), true);
  assert.equal(isConfiguredOrigin("staging", "https://staging.kipnerter.com"), true);
});
test("production/staging origins cannot be substituted or redirected", () => {
  for (const [environment, url] of [
    ["production", "https://staging.kipnerter.com"],
    ["staging", "https://kipnerter.com"],
    ["staging", "https://preview.kipnerter.com"],
    ["staging", "http://staging.kipnerter.com"],
    ["staging", "https://staging.kipnerter.com.evil.test"],
    ["staging", "https://staging.kipnerter.com/"],
    ["production", "https://kipnerter.com:443"],
  ]) assert.equal(isConfiguredOrigin(environment, url), false, `${environment}: ${url}`);
});
