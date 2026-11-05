import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const root = new URL("../../../", import.meta.url);
const manifest=readFileSync(new URL("deploy/lfm3/compose.local-cpu-real.yml",root),"utf8");
const workflow=readFileSync(new URL(".github/workflows/lfm3-local-cpu-real-stage.yml",root),"utf8");
const pre=readFileSync(new URL("scripts/lfm3_local_cpu_preflight.sh",root),"utf8");
const activation=readFileSync(new URL("scripts/lfm3_local_cpu_activate.sh",root),"utf8");
test("real CPU model and web are memory-bounded and isolated from public ingress",()=>{
  for (const x of ['"127.0.0.1:3356:3000"',"1536m","384m","memswap_limit:",
    "internal: true","create_host_path: false","read_only: true",
    "lfm3-1.7b-local","--n-gpu-layers",'"0"', "KIPNERTER_LFM3_ENDPOINTS",
    "restart: \"no\""])assert.ok(manifest.includes(x),x);
  assert.doesNotMatch(manifest,/0\.0\.0\.0:3356/);
  assert.ok(!manifest.includes("Bearer "));
  assert.ok(!manifest.includes("KIPNERTER_LFM3_TOKEN_"));
  assert.ok(!manifest.includes("https://kipnerter.com"));
});

test("production stage is owner-only, preflights resources before any image or model download",()=>{
  for(const x of ["environment: production","persist-credentials: false",
    "github.event.pull_request.user.login == github.repository_owner",
    "github.event.pull_request.head.repo.full_name == github.repository",
    "tags: tag:kipnerter-ci",
    "portal_deploy_target.py --environment production",
    "Fail closed on host RAM, disk, port and existing stage BEFORE any writes",
    "Build real Next.js image and pin official llama.cpp CPU image identity",
    "Download official pinned LFM3 GGUF",
    "Start isolated CPU + Next.js"])assert.ok(workflow.includes(x),x);
  const order=[
    "Fail closed on host RAM, disk, port and existing stage BEFORE any writes",
    "Build real Next.js image and pin official llama.cpp CPU image identity",
    "Download official pinned LFM3 GGUF",
    "Transfer only audited image and official model bytes",
    "Start isolated CPU + Next.js",
  ].map(s=>workflow.indexOf(s));
  assert.ok(order.every(x=>x>0));
  assert.deepEqual(order,[...order].sort((a,b)=>a-b));
  assert.ok(workflow.includes("3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4"));
  assert.ok(workflow.includes("server-b12119"));
  assert.ok(!workflow.includes("docker compose down"));
});

test("preflight preserves existing production availability",()=>{
  for(const x of ["2200000","10000000","3356",
    "kipnerter-lfm3-local-cpu","kipnerter-lfm3-local-web",
    "insufficient spare RAM/disk"])
    assert.ok(pre.includes(x),x);
  for(const x of ["docker rm","docker stop","docker compose up","pkill ","sudo "])
    assert.ok(!pre.includes(x),x);
});

test("real model acceptance verifies publisher hash, answer and scoped rollback",()=>{
  for(const x of ["sha256sum","1099627808","3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4",
    "docker image inspect","com.docker.compose.project","trap rollback ERR",
    "docker rm -f", "What is 2 + 2", "LFM3-1.7B",
    "SIMULATED DEMO RESPONSE", "LOCAL HTTP FIXTURE",
    "LOCAL_CPU_REAL_STAGE_PASS","LOCAL_CPU_STAGE_DEPLOYED"])
    assert.ok(activation.includes(x),x);
  assert.ok(!activation.includes("systemctl"));
  assert.ok(!activation.includes("docker compose down"));
});
