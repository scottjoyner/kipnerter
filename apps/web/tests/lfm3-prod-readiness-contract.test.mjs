import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const root = new URL("../../../", import.meta.url);
const work = readFileSync(new URL(".github/workflows/lfm3-live-product-readiness.yml", root), "utf8");
const probe = readFileSync(new URL("scripts/lfm3_prod_readiness_probe.sh", root), "utf8");

test("live audit uses owner-only approved production Tailnet and never deploys", () => {
  for (const term of [
    "environment: production", "github.event.pull_request.user.login == github.repository_owner",
    "github.event.pull_request.head.repo.full_name == github.repository",
    "persist-credentials: false", "tags: tag:kipnerter-ci",
    "python3 scripts/portal_deploy_target.py --environment production",
    "scripts/lfm3_prod_readiness_probe.sh", "bash -n",
    "no production files, secrets, containers or ingress were changed",
  ]) assert.ok(work.includes(term), "expected safe admission: "+term);
  for (const forbidden of [
    "docker compose up", "docker compose down", "docker run", "docker restart",
    "sudo ", "systemctl ", "pkill ", "killall ", "tailscale up",
  ]) assert.ok(!work.includes(forbidden), "workflow must not mutate: "+forbidden);
});

test("remote audit reads only exact containers, key metadata and anonymous auth", () => {
  for (const term of [
    "kipnerter-web-public-v01", "kipnerter-lfm3-stage-rx480",
    "http://127.0.0.1:3355/", "http://100.78.106.121:19176/v1/models",
    "fs.lstatSync", "s.isFile()", "(s.mode & 0o077)===0",
    "worker_anonymous", "credential_state", "production_writes=none",
    "gateway_available_memory_kib", "gateway_disk_free_kib", "gateway_swap_free_kib",
    "single-worker real staging is not fully admitted",
  ]) assert.ok(probe.includes(term), "expected readonly check: "+term);
  for (const forbidden of [
    "readFileSync", "cat /run/secrets", "printenv", "env |", "docker rm",
    "docker compose up", "docker compose down", "docker restart",
    "sudo ", "systemctl ", "pkill ", "killall ", "curl -X POST",
  ]) assert.ok(!probe.includes(forbidden), "remote probe must not mutate or exfiltrate: "+forbidden);
});
