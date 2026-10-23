import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { privateJson, PRIVATE_RESPONSE_HEADERS } from "../lib/private-response.mjs";

const sectionSource = readFileSync(new URL("../lib/portal.js", import.meta.url), "utf8");
const liveSource = readFileSync(new URL("../app/api/portal/live/route.js", import.meta.url), "utf8");

test("private success, denial, capacity and transient error responses always prevent caching", async () => {
  for (const code of [200, 401, 403, 404, 429, 502, 503]) {
    const response = privateJson({ error: "synthetic-only" }, code);
    assert.equal(response.status, code);
    assert.match(response.headers.get("cache-control"), /private.*no-store/);
    assert.equal(response.headers.get("vary"), "Cookie");
    assert.equal(response.headers.get("x-content-type-options"), "nosniff");
    assert.equal(response.headers.get("pragma"), "no-cache");
    assert.deepEqual(await response.json(), { error: "synthetic-only" });
  }
  assert.ok(Object.isFrozen(PRIVATE_RESPONSE_HEADERS));
});

test("polling gateway cannot return cacheable identity, session or upstream errors", () => {
  assert.match(sectionSource, /import \{ privateJson \} from/);
  for (const [fragment, code] of [
    ['not found', 404],
    ['identity not configured', 503],
    ['authentication required', 401],
    ['gateway not configured', 503],
    ['control plane unavailable', 502],
  ]) {
    assert.ok(sectionSource.includes(`privateJson({ error: "${fragment}" }, ${code})`), fragment);
  }
  assert.match(sectionSource, /return privateJson\(data\)/);
  assert.doesNotMatch(sectionSource, /Response\.json\(/);
});

test("SSE gateway applies private no-store to every auth or capacity denial", () => {
  assert.match(liveSource, /import \{ privateJson \} from/);
  for (const [fragment, code] of [
    ['identity not configured', 503],
    ['authentication required', 401],
    ['gateway not configured', 503],
    ['stream capacity reached', 429],
  ]) {
    assert.ok(liveSource.includes(`privateJson({ error: "${fragment}" }, ${code})`), fragment);
  }
  assert.match(liveSource, /denial\.headers\.set\("Retry-After", "15"\)/);
  assert.match(liveSource, /"Cache-Control": "private, no-store, no-transform"/);
  assert.match(liveSource, /"Vary": "Cookie"/);
  assert.doesNotMatch(liveSource, /Response\.json\(/);
});

test("private route helper does not add CORS or public-cache directives", () => {
  const response = privateJson({ status: "unconfigured" }, 503);
  assert.equal(response.headers.get("access-control-allow-origin"), null);
  assert.equal(response.headers.get("cache-control")?.includes("public"), false);
  assert.equal(response.headers.get("cache-control")?.includes("max-age=0"), true);
});
