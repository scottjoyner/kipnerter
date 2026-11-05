import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const root=new URL("../../../",import.meta.url);
const wf=readFileSync(new URL(".github/workflows/lfm3-live-real-stage-audit.yml",root),"utf8");
const audit=readFileSync(new URL("scripts/lfm3_local_cpu_readonly_audit.py",root),"utf8");
test("independent staging auditor uses restricted production SSH with no writable action",()=>{
  for(const x of ["environment: production", "persist-credentials: false",
    "github.event.pull_request.user.login == github.repository_owner",
    "tags: tag:kipnerter-ci",
    "portal_deploy_target.py --environment production",
    "lfm3_local_cpu_readonly_audit.py","python3 -"])
    assert.ok(wf.includes(x),x);
  for(const bad of ["docker compose up","docker compose down","sudo ","docker restart","docker rm -f","tailscale set"])
    assert.ok(!wf.includes(bad),bad);
});
test("real auditor proves a second response and checks live runtime limits without secrets",()=>{
  for(const x of ["kipnerter-lfm3-local-web", "kipnerter-lfm3-local-cpu",
    "e539c1b888e1148ff34ce00d50ac8a9638b7ff6d6df8918ce27b429026804587",
    "c0a11067c72bb1eb330b8bddbf9869274c195e596bf4fae55fd527102e644b85",
    "127.0.0.1","3356","OOMKilled","Memory","model_only",
    "web_loopback","LFM3-1.7B","SIMULATED DEMO RESPONSE",
    "LOCAL HTTP FIXTURE","LIVE_REAL_LFM3_STAGE_PASS"])
    assert.ok(audit.includes(x),x);
  for(const bad of ["docker run","docker rm","docker restart","docker stop","docker compose",
    "readFileSync","open('/run/secrets","sudo ","systemctl "])
    assert.ok(!audit.includes(bad),bad);
});
