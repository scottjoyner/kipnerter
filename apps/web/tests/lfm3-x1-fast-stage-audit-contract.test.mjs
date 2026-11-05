import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root=new URL("../../../",import.meta.url);
const audit=readFileSync(new URL("scripts/lfm3_x1_fast_stage_audit.py",root),"utf8");
const workflow=readFileSync(new URL(".github/workflows/lfm3-x1-fast-stage-contract.yml",root),"utf8");

test("x1 read-only fast audit verifies exact official model and source",()=>{
  for(const part of [
    "3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4",
    "c2a1dd2978ec7c7215e072bb62080ec2178e5a5b",
    "hashlib.sha256", "git", "rev-parse", "x1-370", "scott",
    "lfm3-1.7b-x1-fast", "MODEL_NAME",
  ]) assert.ok(audit.includes(part),part);
});

test("auditor fails closed on resource/network limits and requires genuine response",()=>{
  for(const part of [
    "127.0.0.1:19181", "127.0.0.1:3357",
    "MemoryMax", "MemoryCurrent", "MemorySwapCurrent", "CPUQuotaPerSecUSec",
    "TasksMax", "ss", "-ltnH", "MemAvailable:",
    "/api/chat/completions", "LFM3-1.7B",
    "SIMULATED DEMO RESPONSE", "LOCAL HTTP FIXTURE",
    "single_generation_latency_ms=", "sample_count=1", "15000",
  ]) assert.ok(audit.includes(part),part);
  assert.equal((audit.match(/\/api\/chat\/completions/g)||[]).length,1,
    "one real inference only");
});

test("new CI only verifies code; it cannot reach or deploy to the fleet",()=>{
  for(const part of [
    "permissions:", "contents: read", "python3 -m py_compile",
    "node --test apps/web/tests/lfm3-x1-fast-stage-audit-contract.test.mjs",
  ]) assert.ok(workflow.includes(part),part);
  for(const bad of [
    "tailscale/github-action", "environment: production", "workflow_dispatch",
    "TS_OAUTH_SECRET", "secrets.", "docker compose up", "systemd-run",
    "sudo ", "deploy", "ssh -o StrictHostKeyChecking=no",
  ]) assert.ok(!workflow.includes(bad),bad);
  for(const bad of [
    "docker run", "docker rm", "docker restart", "systemctl restart",
    "systemctl stop", "systemctl start", "systemd-run", "sudo ",
    "os.system", "Popen(", "ssh-keyscan", "StrictHostKeyChecking=no",
  ]) assert.ok(!audit.includes(bad),bad);
});
