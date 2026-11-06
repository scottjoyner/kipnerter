import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root=new URL("../../../",import.meta.url);
const caddy=readFileSync(new URL("infra/caddy/Caddyfile.lfm3-protected-preview.example",root),"utf8");
const audit=readFileSync(new URL("scripts/lfm3_protected_preview_audit.py",root),"utf8");
const workflow=readFileSync(new URL(".github/workflows/lfm3-preview-edge-contract.yml",root),"utf8");

test("separate beta hostname is authenticated and has only TLS-verified private backend",()=>{
  for(const x of [
    "preview.kipnerter.com {", "basic_auth {",
    "beta __REPLACE_WITH_OPERATOR_GENERATED_BCRYPT_HASH__",
    'header Cache-Control "private, no-store"',
    "reverse_proxy https://x1-370.tailcb8954.ts.net:8450",
    "header_up Host x1-370.tailcb8954.ts.net:8450",
  ]) assert.ok(caddy.includes(x),x);
  assert.equal((caddy.match(/preview\.kipnerter\.com \{/g)||[]).length,1);
  assert.ok(!caddy.includes("0.0.0.0:19181"),"never publish model");
  assert.ok(!/\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{45,}/.test(caddy),
    "no real bcrypt hash in repo");
});
test("all non-preview production routes are explicitly preserved",()=>{
  for(const x of [
    "kipnerter.com, www.kipnerter.com {",
    "reverse_proxy kipnerter-web-public-v01:3000",
    "api.kipnerter.com {",
    "reverse_proxy spatial-api:8000",
    "reverse_proxy spatial-minio:9000",
    "reverse_proxy api:8000",
    "scottjoyner.dev, admin.scottjoyner.dev {",
    "reverse_proxy web:3000",
  ]) assert.ok(caddy.includes(x),x);
  const previewBlock=caddy.split("preview.kipnerter.com {")[1]?.split("\n}\n")[0];
  assert.ok(previewBlock && previewBlock.indexOf("basic_auth") < previewBlock.indexOf("reverse_proxy"),
    "authentication precedes upstream proxy");
});
test("live audit verifies no bypass, real assets/inference, release identity and rollback",()=>{
  for(const x of [
    "preview.password", "Caddyfile.before", "Caddyfile.candidate",
    "LIVE_SHA", "OLD_SHA", "CADDY_IMAGE",
    "stat.S_IMODE", "0o600",
    "wrong", "401", "static", "/api/chat/completions",
    "LFM3-1.7B", "15000",
    "public_site_unchanged=true", "public_release=false",
    "PROTECTED_PREVIEW_LIVE_PASS",
  ]) assert.ok(audit.includes(x),x);
  assert.equal((audit.match(/"content": "What is 2 \+ 2\?/g)||[]).length,1,
    "single real-generation request only");
  for(const forbidden of [
    "docker run", "docker stop", "docker rm", "docker compose",
    "caddy reload", "systemctl restart", "subprocess.Popen",
    "os.system(", "ssh-keyscan",
  ]) assert.ok(!audit.includes(forbidden),forbidden);
});
test("CI never accesses production hosts or private credentials",()=>{
  for(const x of [
    "permissions:", "contents: read",
    "persist-credentials: false",
    "python3 -m py_compile scripts/lfm3_protected_preview_audit.py",
    "node --test apps/web/tests/lfm3-preview-edge-contract.test.mjs",
  ]) assert.ok(workflow.includes(x),x);
  for(const x of [
    "environment: production", "tailscale/github-action",
    "secrets.", "ssh ", "docker exec", "Caddyfile.before",
  ]) assert.ok(!workflow.includes(x),x);
});
