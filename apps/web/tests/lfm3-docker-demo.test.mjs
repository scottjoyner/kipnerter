import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const manifest = readFileSync(
  new URL("../../../deploy/lfm3/demo/compose.simulated.yml", import.meta.url), "utf8");
const fixture = readFileSync(
  new URL("../../../deploy/lfm3/demo/fixture_server.py", import.meta.url), "utf8");
const ignored = readFileSync(
  new URL("../.dockerignore", import.meta.url), "utf8");

test("local demo binds the web only to loopback, never publishes simulated model", () => {
  assert.match(manifest, /127\.0\.0\.1:\$\{KIPNERTER_LFM3_DEMO_PORT:-3360\}:3000/);
  assert.match(manifest, /internal: true/);
  assert.match(manifest, /read_only: true/);
  assert.match(manifest, /no-new-privileges:true/);
  assert.doesNotMatch(manifest, /(?:^|\n)\s+-\s*["']?0\.0\.0\.0:/);
  assert.doesNotMatch(manifest, /Bearer\s+[A-Za-z0-9]+/);
  assert.doesNotMatch(manifest, /KIPNERTER_LFM3_SECRET_DIR|\/run\/secrets|100\.78\.106\.121/);
  assert.match(manifest, /http:\/\/fixture:8077/);
  assert.match(manifest, /simulated-local-demo/);
});

test("simulated model is clearly labeled, model-only and logs no user messages", () => {
  assert.match(fixture, /SIMULATED DEMO RESPONSE/);
  assert.match(fixture, /NOT REAL MODEL INFERENCE/);
  assert.match(fixture, /def log_message/);
  assert.match(fixture, /pass  # do not put demo prompts/);
  assert.match(fixture, /not isinstance\(payload\.get\("messages"\), list\)/);
  assert.match(fixture, /payload\.get\("tools"\)/);
});

test("web container excludes developer credentials and local build files", () => {
  for (const item of ["node_modules", ".next", ".env", ".env.*", "*.pem", "*.key", "secrets"]) {
    assert.ok(ignored.split("\n").includes(item), item);
  }
});
