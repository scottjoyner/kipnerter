import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const compose = readFileSync(new URL("../../../deploy/lfm3/compose.staging.yml", import.meta.url), "utf8");

test("approved LFM3 staging manifest keeps ports private and never creates secret directories", () => {
  assert.match(compose, /127\.0\.0\.1:3354:3000/);
  assert.doesNotMatch(compose, /(?:^|\n)\s+-\s*["']?0\.0\.0\.0:/);
  assert.match(compose, /read_only: true/);
  assert.match(compose, /create_host_path: false/);
  assert.match(compose, /KIPNERTER_LFM3_SECRET_DIR:\?A provisioned root-only directory/);
  assert.match(compose, /restart: "no"/);
  assert.match(compose, /external: true/);
});

test("stage roster prefers both distinct GPU hosts with a separate CPU overflow", () => {
  const rosterText = compose.match(/KIPNERTER_LFM3_ENDPOINTS:\s*>-\s*\n\s*(\[[^\n]+\])/);
  assert.ok(rosterText, "roster must remain parseable, explicit JSON");
  const nodes = JSON.parse(rosterText[1]);
  assert.equal(nodes.length,3);
  assert.deepEqual(nodes.map(x=>x.name),["r9700","rx480","optiplex"]);
  assert.deepEqual(nodes.map(x=>x.role),["interactive","interactive","overflow"]);
  assert.equal(new Set(nodes.map(x=>new URL(x.baseUrl).hostname)).size,3);
  assert.ok(nodes.every(x=>x.maxInflight===1&&x.credentialEnv?.startsWith("KIPNERTER_LFM3_TOKEN_")));
  assert.ok(nodes.some(x=>x.name==="r9700"&&x.disableThinking===true&&x.maxOutputTokens===256));
  assert.ok(nodes.every(x=>!x.baseUrl.includes("x1-370")));
});

test("staging compose has no bearer key material or public cutover", () => {
  assert.doesNotMatch(compose,/Bearer\s+[A-Za-z0-9-]+/);
  assert.doesNotMatch(compose,/api[_-]?key:\s*["']?[A-Za-z0-9]{16}/i);
  assert.doesNotMatch(compose, /https?:\/\/kipnerter\.com/);
  assert.match(compose, /kipnerter-lfm3-stage-provisioned/);
});
