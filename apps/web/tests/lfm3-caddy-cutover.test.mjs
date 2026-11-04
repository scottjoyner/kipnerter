import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const candidate = readFileSync(
  new URL("../../../deploy/lfm3/caddy.phase1.candidate.Caddyfile", import.meta.url),
  "utf8",
);

test("phase-one Caddy candidate cannot silently become a public deployment command", () => {
  assert.match(candidate, /UNAPPLIED PHASE-1 CUTOVER CANDIDATE/);
  assert.match(candidate, /SHARED abuse\/rate limiter/);
  assert.match(candidate, /approved per-node secret provisioning/);
  assert.doesNotMatch(candidate, /(?:docker|kubectl|systemctl)\s+(?:run|up|reload|apply)/);
  assert.doesNotMatch(candidate, /\b(?:Bearer|Authorization:)\s+[A-Za-z0-9-]{16,}/);
});

test("only canonical POST chat requests are diverted to the staged LFM3 service", () => {
  const match = candidate.match(
    /@canonical_lfm3_chat\s*\{([^}]+)\}/,
  );
  assert.ok(match);
  assert.match(match[1], /host kipnerter\.com/);
  assert.match(match[1], /path \/api\/chat\/completions/);
  assert.match(match[1], /method POST/);
  assert.doesNotMatch(match[1], /\/api\/chat\/research|\/api\/auth/);
  assert.match(candidate, /handle @canonical_lfm3_chat\s*\{/);
  assert.match(candidate, /reverse_proxy 127.0.0.1:8094/);
  assert.equal((candidate.match(/reverse_proxy 127.0.0.1:8094/g) || []).length, 1);
});

test("same site retains existing fallback site, API and admin backends", () => {
  assert.match(candidate, /handle\s*\{\s*reverse_proxy kipnerter-web-public-v01:3000\s*\}/);
  assert.match(candidate, /api\.kipnerter\.com\s*\{/);
  assert.match(candidate, /reverse_proxy spatial-api:8000/);
  assert.match(candidate, /reverse_proxy spatial-minio:9000/);
  assert.match(candidate, /reverse_proxy api:8000/);
  assert.match(candidate, /scottjoyner\.dev, admin\.scottjoyner\.dev/);
  assert.match(candidate, /reverse_proxy web:3000/);
});

test("canonical chat route has small request body and sanitized client IP", () => {
  assert.match(candidate, /request_body\s*\{\s*max_size 8KB\s*\}/);
  assert.match(candidate, /header_up X-Forwarded-For \{remote_host\}/);
  assert.match(candidate, /header_up X-Real-IP \{remote_host\}/);
  // No private research endpoint becomes public before operator auth is deployed.
  assert.doesNotMatch(candidate, /path \/api\/chat\/research/);
});

test("phase one must pass through a shared limiter, never directly to the unkeyed Next.js stage", () => {
  assert.match(candidate, /reverse_proxy 127\\.0\\.0\\.1:8094/);
  assert.doesNotMatch(candidate, /reverse_proxy kipnerter-lfm3-stage-provisioned:3000/);
  assert.match(candidate, /header_up X-Real-IP \\{remote_host\\}/);
});
