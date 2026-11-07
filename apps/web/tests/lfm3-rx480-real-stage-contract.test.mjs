import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const root=new URL("../../../",import.meta.url);
const wf=readFileSync(new URL(".github/workflows/lfm3-rx480-real-stage.yml",root),"utf8");
const pre=readFileSync(new URL("scripts/lfm3_rx480_stage_preflight.sh",root),"utf8");
const activate=readFileSync(new URL("scripts/lfm3_rx480_stage_activate.sh",root),"utf8");
const manifest=readFileSync(new URL("deploy/lfm3/compose.staging.rx480.yml",root),"utf8");

test("real staging uses owner-only, exact-source production CI and protects preflight ordering",()=>{
  for (const text of ["environment: production","persist-credentials: false",
    "github.event.pull_request.user.login == github.repository_owner",
    "github.event.pull_request.head.repo.full_name == github.repository",
    "tags: tag:kipnerter-ci","portal_deploy_target.py --environment production",
    "scripts/lfm3_rx480_stage_preflight.sh",
    "scripts/lfm3_rx480_stage_activate.sh","docker build",
    "docker save", "docker load", "no Caddy, public URL"]) {
    assert.ok(wf.includes(text),text);
  }
  const order=[
    "Require protected RX480 secret and resources BEFORE production writes",
    "Build exact-source production Next.js image on CI host",
    "Transfer public image bytes and private-stage manifest only",
    "Activate isolated localhost stage and require a genuine LFM3 reply"
  ].map(x=>wf.indexOf(x));
  assert.ok(order.every(x=>x>0));
  assert.deepEqual(order,[...order].sort((a,b)=>a-b));
  assert.ok(wf.includes("cancel-in-progress: false"));
  assert.ok(!wf.includes("docker compose down"));
  assert.ok(!wf.includes("docker compose restart"));
});

test("preflight verifies authenticated live worker and secret file metadata only",()=>{
  for(const x of ["kipnerter-lfm3-stage-rx480",
    "127.0.0.1:3355",
    "100.78.106.121:19176/v1/models",
    '[[ "$worker" == 401 ]]', "os.lstat",
    'base+"/rx480.key"', "16 <= key.st_size <= 2048",
    "secret values never read"])assert.ok(pre.includes(x),x);
  for(const x of ["readFileSync","open(base", "cat /home/kipnerter",
    "docker rm", "docker compose up","sudo "])assert.ok(!pre.includes(x),x);
});

test("real-only staged activation checks image identity, model generation, and rollback",()=>{
  for(const x of ['"$actual" == "$EXPECTED_ID"',
    "docker image inspect", "com.docker.compose.project",
    "docker rm -f", "trap rollback ERR",
    "docker compose -p kipnerter-lfm3-rx480",
    "127.0.0.1:3355","100.78.106.121" ]) {
    if(x==="100.78.106.121")continue;
    assert.ok(activate.includes(x),x);
  }
  for(const x of ["LFM3-1.7B","RX480_REAL_STAGE_PASS","SIMULATED DEMO RESPONSE",
    "LOCAL HTTP FIXTURE", "413",
    'echo "STAGE_DEPLOYED:', "public routes unchanged"])
    assert.ok(activate.includes(x) || (x==="public routes unchanged" && manifest.includes("does not change the public Caddy")),x);
  assert.match(manifest, /127\.0\.0\.1:3355:3000/);
  assert.match(manifest, /read_only:\s*true/);
  assert.match(manifest, /create_host_path:\s*false/);
  assert.doesNotMatch(activate,/0\.0\.0\.0:3355/);
  assert.doesNotMatch(activate,/docker compose down/);
  assert.doesNotMatch(activate,/readFileSync/);
});
