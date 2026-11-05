import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const root=new URL("../../../",import.meta.url);
const manifest=readFileSync(new URL("deploy/lfm3/compose.local-cpu-real-v2.yml",root),"utf8");
const workflow=readFileSync(new URL(".github/workflows/lfm3-local-cpu-fast-retry.yml",root),"utf8");
const script=readFileSync(new URL("scripts/lfm3_local_cpu_activate_v2.sh",root),"utf8");

test("web gets a host-reachable bridge, model stays isolated on separate private network",()=>{
  assert.match(manifest,/127\.0\.0\.1:3356:3000/);
  assert.match(manifest,/model_only:\s*\n\s*internal: true/);
  assert.match(manifest,/web_loopback:\s*\n\s*driver: bridge/);
  assert.match(manifest,/lfm3-local-web:[\s\S]*?networks:\s*\n\s*-\s*model_only\s*\n\s*-\s*web_loopback/);
  assert.match(manifest,/lfm3-local-cpu:[\s\S]*?networks:\s*\n\s*-\s*model_only[\s\S]*?# NO host port/);
  assert.ok(!manifest.includes("0.0.0.0:3356"));
  assert.ok(!manifest.includes("KIPNERTER_LFM3_TOKEN_"));
});

test("fast retry uses only source, runtime and model already immutably verified on production",()=>{
  for(const s of ["environment: production","persist-credentials: false",
    "github.event.pull_request.user.login == github.repository_owner",
    "portal_deploy_target.py --environment production",
    "CERTIFIED_SOURCE_SHA: 6f910de222e2b21ddbe1486584f3cc8da7274b22",
    "CERTIFIED_RUN: '42075860987'",
    "CERTIFIED_MODEL_SHA: 3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4",
    "CERTIFIED_WEB_IMAGE_ID: sha256:e539c1b888e1148ff34ce00d50ac8a9638b7ff6d6df8918ce27b429026804587",
    "CERTIFIED_SERVER_IMAGE_ID: sha256:c0a11067c72bb1eb330b8bddbf9869274c195e596bf4fae55fd527102e644b85",
    "sha256sum --check --status",
    "ln '$old/models/LFM3-1.7B-Q4_K_M.gguf'",
    "lfm3_local_cpu_preflight.sh",
    "lfm3_local_cpu_activate_v2.sh"])assert.ok(workflow.includes(s),s);
  assert.ok(!workflow.includes("docker build"));
  assert.ok(!workflow.includes("docker pull"));
  assert.ok(!workflow.includes("docker compose down"));
});

test("failed staging diagnoses states without reading model secrets, and rolls back only its containers",()=>{
  for(const s of ["compose.local-cpu-real-v2.yml",
    "stage_container=$name status=$status oom=$oom exit_code=$exit_code",
    "com.docker.compose.project","docker rm -f",
    "LOCAL_CPU_REAL_STAGE_PASS","SIMULATED DEMO RESPONSE","LOCAL HTTP FIXTURE",
    "sha256sum", "1099627808"])assert.ok(script.includes(s),s);
  assert.ok(!script.includes("docker compose down"));
  assert.ok(!script.includes("sudo "));
});
