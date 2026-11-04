import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const nginx = readFileSync(
  new URL("../../../deploy/lfm3/edge/nginx.conf", import.meta.url), "utf8");
const compose = readFileSync(
  new URL("../../../deploy/lfm3/edge/compose.edge-candidate.yml", import.meta.url), "utf8");
const caddy = readFileSync(
  new URL("../../../deploy/lfm3/caddy.phase1.candidate.Caddyfile", import.meta.url), "utf8");

test("shared limiter listens on Caddy namespace loopback with no exposed port", () => {
  assert.match(nginx, /listen 127\.0\.0\.1:8094;/);
  assert.doesNotMatch(nginx, /listen\s+(?:0\.0\.0\.0|\[::\]|80|443):?8094?/);
  assert.match(compose, /network_mode: "container:kipnerter-caddy-1"/);
  assert.doesNotMatch(compose, /(?:^|\n)\s*ports:\s*(?:\n|$)/);
  assert.match(compose, /read_only: true/);
  assert.match(compose, /create_host_path: false/);
  assert.match(compose, /no-new-privileges:true/);
  assert.match(compose, /cap_drop:\s*\n\s*- ALL/);
  assert.match(compose, /KIPNERTER_LFM3_EDGE_IMAGE:\?Approved immutable nginx digest/);
});

test("Nginx applies per-client and global shared-memory rate limits plus concurrency cap", () => {
  assert.match(nginx, /map \$http_x_real_ip \$lfm3_client_key/);
  assert.match(nginx, /"" \$remote_addr;/);
  assert.match(nginx, /limit_req_zone \$lfm3_client_key zone=lfm3_client:1m rate=6r\/m;/);
  assert.match(nginx, /limit_req_zone \$server_name zone=lfm3_global:1m rate=30r\/m;/);
  assert.match(nginx, /limit_conn_zone \$server_name zone=lfm3_connections:1m;/);
  assert.match(nginx, /limit_req zone=lfm3_client burst=2 nodelay;/);
  assert.match(nginx, /limit_req zone=lfm3_global burst=5 nodelay;/);
  assert.match(nginx, /limit_conn lfm3_connections 2;/);
  assert.match(nginx, /limit_req_status 429;/);
  assert.match(nginx, /limit_conn_status 429;/);
});

test("edge limiter only allows canonical chat POST and never logs prompts", () => {
  assert.match(nginx, /client_max_body_size 8k;/);
  assert.match(nginx, /access_log off;/);
  assert.match(nginx, /if \(\$request_method != POST\) \{ return 405; \}/);
  assert.match(nginx, /location = \/api\/chat\/completions/);
  assert.match(nginx, /proxy_pass http:\/\/kipnerter-lfm3-stage-provisioned:3000;/);
  assert.match(nginx, /proxy_set_header X-Real-IP \$lfm3_client_key;/);
  assert.match(nginx, /location \/ \{ return 404; \}/);
  assert.doesNotMatch(nginx, /authorization.*bearer\s+[A-Za-z0-9]/i);
});

test("Caddy uses the loopback limiter and sanitizes client IP", () => {
  assert.match(caddy, /reverse_proxy 127\.0\.0\.1:8094/);
  assert.match(caddy, /header_up X-Real-IP \{remote_host\}/);
  assert.match(caddy, /header_up X-Forwarded-For \{remote_host\}/);
  assert.doesNotMatch(caddy, /reverse_proxy kipnerter-lfm3-stage-provisioned:3000/);
});
