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

const rx480Mvp = readFileSync(new URL("../../../deploy/lfm3/compose.staging.rx480.yml", import.meta.url), "utf8");

test("RX480 MVP is a real private Next.js service, not a simulated response", () => {
  assert.match(rx480Mvp, /container_name:\s*kipnerter-lfm3-stage-rx480/);
  assert.match(rx480Mvp, /127\.0\.0\.1:3355:3000/);
  assert.match(rx480Mvp, /KIPNERTER_LFM3_STAGE_IMAGE:\?Verified pinned staging image required/);
  assert.match(rx480Mvp, /KIPNERTER_LFM3_SECRET_DIR:\?Approved private directory required/);
  assert.match(rx480Mvp, /read_only:\s*true/);
  assert.match(rx480Mvp, /create_host_path:\s*false/);
  assert.match(rx480Mvp, /restart:\s*"no"/);
  assert.match(rx480Mvp, /external:\s*true/);
  assert.doesNotMatch(rx480Mvp, /0\.0\.0\.0:3355/);
  assert.doesNotMatch(rx480Mvp, /fixture_server|SIMULATED DEMO|localhost fixture/i);
});

test("RX480 MVP roster admits only the exact authenticated real worker", () => {
  const line=rx480Mvp.match(/KIPNERTER_LFM3_ENDPOINTS:\s*>-\s*\n\s*(\[[^\n]+\])/);
  assert.ok(line, "one-worker roster must be explicit JSON");
  const workers=JSON.parse(line[1]);
  assert.equal(workers.length,1);
  assert.deepEqual(workers[0], {
    name:"rx480",baseUrl:"http://100.78.106.121:19176",
    model:"lfm3-1.7b-rx480",adapter:"openai",role:"interactive",
    maxInflight:1,maxOutputTokens:256,
    credentialEnv:"KIPNERTER_LFM3_TOKEN_RX480"
  });
  assert.doesNotMatch(rx480Mvp,/Bearer\s+[A-Za-z0-9-]+/);
  assert.doesNotMatch(rx480Mvp,/https?:\/\/kipnerter\.com/);
});
