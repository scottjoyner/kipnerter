import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { endpointConfig } from "../../apps/web/lib/lfm3-fleet.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = p => fs.readFileSync(path.join(root, p), "utf8");
const compose = read("deploy/lfm3/compose.staging.cpu.yml");
const preflight = read("scripts/lfm3_cpu_stage_preflight.sh");
const activation = read("scripts/lfm3_cpu_stage_activate.sh");

test("CPU stage uses only independent resources and no RX480 secret, worker or network", () => {
  for (const file of [compose, preflight, activation]) {
    assert.doesNotMatch(file, /rx480[.]key|KIPNERTER_LFM3_TOKEN_RX480|100[.]78[.]106[.]121/i);
  }
  assert.match(compose, /127[.]0[.]0[.]1:3363:3000/);
  assert.doesNotMatch(compose, /network_mode:\s*host|privileged:\s*true|kipnerter_frontend/);
  assert.match(compose, /internal:\s*true/);
  assert.match(compose, /create_host_path:\s*false/);
  assert.match(compose, /read_only:\s*true/);
  assert.match(compose, /cap_drop:\s*\[ALL\]/);
  assert.match(compose, /maxInflight\\?":1/);
  assert.match(compose, /lfm3-1[.]7b-cpu/);
  assert.equal((compose.match(/ports:/g) || []).length, 1, "model may not publish ports");
});

test("API accepts the credential-free, exact-model local CPU endpoint", () => {
  const nodes = endpointConfig(JSON.stringify([{
    name: "cpu_stage", baseUrl: "http://kipnerter-lfm3-stage-cpu-model:8080",
    model: "lfm3-1.7b-cpu", adapter: "openai", role: "interactive",
    maxInflight: 1, maxOutputTokens: 128,
  }]));
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].credentialEnv, null);
  assert.equal(nodes[0].model, "lfm3-1.7b-cpu");
});

test("preflight fails closed outside authorized deployment principal", () => {
  if (process.getuid?.() === 0) return; // root CI environments may vary
  const run = spawnSync("bash", ["scripts/lfm3_cpu_stage_preflight.sh"], {
    cwd: root, encoding: "utf8", timeout: 5000,
  });
  assert.equal(run.status, 3);
  assert.match(run.stderr, /CPU_STAGE_HOLD/);
});

test("activation fails closed unless an operator explicitly opts in", () => {
  const run = spawnSync("bash", ["scripts/lfm3_cpu_stage_activate.sh"], {
    cwd: root, encoding: "utf8", timeout: 5000,
    env: { ...process.env, KIPNERTER_LFM3_CPU_STAGE_APPROVED: "" },
  });
  assert.equal(run.status, 3);
  assert.match(run.stderr, /approval missing/);
  assert.match(activation, /3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4/);
  assert.match(activation, /--no-build --pull never/);
  assert.match(activation, /CPU_STAGE_REAL_PASS/);
});

test("scripts pass bash syntax checks", () => {
  for (const file of ["scripts/lfm3_cpu_stage_preflight.sh", "scripts/lfm3_cpu_stage_activate.sh"]) {
    const run = spawnSync("bash", ["-n", file], { cwd: root, encoding: "utf8" });
    assert.equal(run.status, 0, run.stderr);
  }
});
