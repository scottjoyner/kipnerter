import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, chmodSync, symlinkSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveFleetNodeCredential } from "../lib/lfm3-credentials.mjs";

const node = { name: "rx480", credentialEnv: "KIPNERTER_LFM3_TOKEN_RX480" };
const fakeKey = "example-test-key-not-a-real-credential";

test("a secure file-mounted model credential is preferred over env credentials", () => {
  const dir = mkdtempSync(join(tmpdir(), "lfm3-key-"));
  try {
    writeFileSync(join(dir, "rx480.key"), fakeKey + "\n", { mode: 0o600 });
    assert.equal(resolveFleetNodeCredential(node, {
      root: dir, env: { KIPNERTER_LFM3_TOKEN_RX480: "legacy-example-credential-123" },
    }), fakeKey);
    assert.equal(resolveFleetNodeCredential(node, { root: dir, env: {} }), fakeKey);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
test("invalid key modes or symlinks fail closed even when legacy env exists", () => {
  const dir = mkdtempSync(join(tmpdir(), "lfm3-key-"));
  const other = mkdtempSync(join(tmpdir(), "lfm3-target-"));
  const fallback = { KIPNERTER_LFM3_TOKEN_RX480: "legacy-example-credential-123" };
  try {
    const key = join(dir, "rx480.key");
    writeFileSync(key, fakeKey, { mode: 0o600 });
    chmodSync(key, 0o644);
    assert.equal(resolveFleetNodeCredential(node, { root: dir, env: fallback }), "");
    rmSync(key);
    writeFileSync(join(other, "key"), fakeKey, { mode: 0o600 });
    symlinkSync(join(other, "key"), key);
    assert.equal(resolveFleetNodeCredential(node, { root: dir, env: fallback }), "");
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(other, { recursive: true, force: true });
  }
});
test("missing files use compatible server-only environment references", () => {
  const dir = mkdtempSync(join(tmpdir(), "lfm3-key-"));
  try {
    const env = { KIPNERTER_LFM3_TOKEN_RX480: "legacy-example-credential-123" };
    assert.equal(resolveFleetNodeCredential(node, { root: dir, env }), env.KIPNERTER_LFM3_TOKEN_RX480);
    assert.equal(resolveFleetNodeCredential(node, { root: dir, env: {} }), "");
    assert.equal(resolveFleetNodeCredential({ name: "rx480", credentialEnv: null }, {
      root: dir, env: { KIPNERTER_LFM3_BEARER: fakeKey },
    }), fakeKey);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
test("invalid identities, unsafe secrets and path traversal never read a key", () => {
  const dir = mkdtempSync(join(tmpdir(), "lfm3-key-"));
  try {
    assert.equal(resolveFleetNodeCredential({ ...node, name: "../../other" }, { root: dir }), "");
    assert.equal(resolveFleetNodeCredential({ ...node, credentialEnv: "NEXT_PUBLIC_KEY" }, { root: dir }), "");
    assert.equal(resolveFleetNodeCredential(node, { root: dir,
      env: { KIPNERTER_LFM3_TOKEN_RX480: "short" } }), "");
    assert.equal(resolveFleetNodeCredential(node, { root: dir,
      env: { KIPNERTER_LFM3_TOKEN_RX480: "valid-looking-key\r\nInjected-Header: nope" } }), "");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
