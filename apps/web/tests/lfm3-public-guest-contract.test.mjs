import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root = new URL("../../../", import.meta.url);
const nginx = readFileSync(new URL("infra/nginx/lfm3-public-guest.conf", root), "utf8");
const caddy = readFileSync(new URL("infra/caddy/Caddyfile.lfm3-public-guest.example", root), "utf8");
const audit = readFileSync(new URL("scripts/lfm3_public_guest_audit.py", root), "utf8");
const runbook = readFileSync(new URL("deploy/lfm3/PUBLIC_GUEST_RELEASE.md", root), "utf8");
const workflow = readFileSync(new URL(".github/workflows/lfm3-public-guest-contract.yml", root), "utf8");

test("public entry redirects only Chat, preserving original site and API domains", () => {
  for (const expected of [
    "kipnerter.com, www.kipnerter.com {",
    "@lfm3_guest_entry path /chat /chat/*",
    "redir @lfm3_guest_entry https://preview.kipnerter.com{uri} 302",
    "@native_lfm3_api path /api/chat/completions",
    "handle @native_lfm3_api {",
    "reverse_proxy kipnerter-web-public-v01:3000",
    "api.kipnerter.com {",
    "reverse_proxy spatial-api:8000",
    "reverse_proxy spatial-minio:9000",
    "reverse_proxy api:8000",
    "scottjoyner.dev, admin.scottjoyner.dev {",
  ]) assert.ok(caddy.includes(expected), expected);
});

test("guest paths are narrow and all other preview paths preserve operator Basic Auth", () => {
  for (const expected of [
    "@public_chat path /chat /chat/*",
    "@public_api path /api/chat/completions",
    "@public_assets path /_next/static/*",
    "handle @public_chat {",
    "handle @public_api {",
    "handle @public_assets {",
    "header_up X-Kipnerter-Client-IP {remote_host}",
    "header_up -Authorization",
    "request_body {",
    "max_size 8192",
    "reverse_proxy kipnerter-lfm3-public-gate-v01:8080",
    "basic_auth {",
    "beta BCRYPT_HASH_PLACEHOLDER",
  ]) assert.ok(caddy.includes(expected), expected);
  const operatorHandle = caddy.indexOf("\n    handle {\n        basic_auth {");
  assert.ok(operatorHandle > caddy.indexOf("handle @public_assets"),
    "authentication remains on the last fallback handler");
  // One trusted identity assignment for canonical API and three for preview routes.
  assert.equal((caddy.match(/header_up X-Kipnerter-Client-IP \{remote_host\}/g) || []).length, 4);
  assert.ok(!/\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{45,}/.test(caddy),
    "no operator bcrypt hash committed");
});

test("Nginx globally enforces bounded public generation and valid upstream TLS", () => {
  for (const expected of [
    "limit_req_zone $http_x_kipnerter_client_ip zone=lfm3_ip:1m rate=3r/m;",
    "limit_req_zone $server_name zone=lfm3_global:1m rate=12r/m;",
    "limit_conn_zone $server_name zone=lfm3_active:1m;",
    "limit_req zone=lfm3_ip burst=2 nodelay;",
    "limit_req zone=lfm3_global burst=4 nodelay;",
    "limit_conn lfm3_active 1;",
    "limit_req_status 429;",
    "limit_conn_status 429;",
    "client_max_body_size 8192;",
    "if ($http_x_kipnerter_client_ip = \"\") { return 403; }",
    "limit_except POST { deny all; }",
    "limit_except GET HEAD { deny all; }",
    "proxy_ssl_server_name on;",
    "proxy_ssl_name x1-370.tailcb8954.ts.net;",
    "proxy_ssl_verify on;",
    "proxy_ssl_trusted_certificate /etc/nginx/verified-host-ca.pem;",
    "proxy_ssl_verify_depth 6;",
    "proxy_pass https://x1-370.tailcb8954.ts.net:8450;",
    "access_log off;",
  ]) assert.ok(nginx.includes(expected), expected);
  assert.equal((nginx.match(/proxy_ssl_verify on;/g) || []).length, 2);
  assert.equal((nginx.match(/proxy_ssl_verify_depth 6;/g) || []).length, 2);
  assert.ok(!nginx.includes("proxy_ssl_verify off"), "never disable certificate trust");
});

test("live audit validates identities without exposing credentials or changing hosts", () => {
  for (const expected of [
    "PUBLIC_CADDY_SHA", "PREVIOUS_CADDY_SHA", "NGINX_CONFIG_SHA", "CA_BUNDLE_SHA",
    "NGINX_IMAGE", "CADDY_IMAGE",
    "PortBindings", "ReadonlyRootfs", "NanoCpus", "PidsLimit", "CapDrop",
    "/api/chat/fleet-status", "200, 302, 200, 401, 401, 200",
    "/_next/static/", "LFM3-1.7B", "PUBLIC_GUEST_LFM3_RELEASE_PASS",
    "sample_count=1",
  ]) assert.ok(audit.includes(expected), expected);
  assert.equal((audit.match(/"content": "What is 2 \+ 2\?/g) || []).length, 1);
  for (const bad of [
    "docker run", "docker stop", "docker restart", "docker rm",
    "caddy reload", "systemctl restart", "subprocess.Popen", "os.system(",
    "preview.password",
  ]) assert.ok(!audit.includes(bad), bad);
});

test("synthetic CI has no production network, secrets, or mutation permissions", () => {
  for (const expected of [
    "permissions:", "contents: read", "persist-credentials: false",
    "python3 -m py_compile scripts/lfm3_public_guest_audit.py",
    "node --test apps/web/tests/lfm3-public-guest-contract.test.mjs",
  ]) assert.ok(workflow.includes(expected), expected);
  for (const bad of [
    "tailscale/github-action", "environment: production", "secrets.",
    "docker run", "ssh ", "workflow_dispatch", "curl https://",
  ]) assert.ok(!workflow.includes(bad), bad);
});

test("rollback runbook pins current live Caddy digest, not stale guest candidate", () => {
  const live = audit.match(/^PUBLIC_CADDY_SHA = "([a-f0-9]{64})"$/m)?.[1];
  const prior = audit.match(/^PREVIOUS_CADDY_SHA = "([a-f0-9]{64})"$/m)?.[1];
  const intermediate = audit.match(/^GUEST_BEFORE_IOS_SHA = "([a-f0-9]{64})"$/m)?.[1];
  assert.ok(live && prior && intermediate, "reviewed exact SHA pins");
  assert.notEqual(live, intermediate, "current and historical Caddy are distinct");
  assert.ok(runbook.includes("| **Current live public Caddyfile**"), "current file labeled precisely");
  assert.ok(runbook.includes(`**\`${live}\`**`), "runbook must identify current live SHA");
  assert.ok(runbook.includes(`\`${prior}\``), "runbook must pin protected rollback SHA");
  assert.ok(runbook.includes(`\`${intermediate}\``), "historical guest candidate kept distinguishable");
  assert.ok(runbook.includes("If any live file or backup differs, **HOLD**"),
    "rollback must fail closed on unexpected live or backup identity");
});
