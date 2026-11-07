// Single-worker, private-loopback-only demo. Not a production promotion gate.
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const DEMO_PORT = 3356;
export const DEMO_CONTAINER = "kipnerter-lfm3-demo-rx480";
export const DEMO_MODEL = "LFM3-1.7B";
const DEMO_URL = "http://127.0.0.1:3356";
const SCRIPT = `
const fs = require("node:fs");
const out = { keyStatus: "missing", rosterReady: false, stage: process.env.KIPNERTER_ENV === "staging" };
try {
  const key = fs.lstatSync("/run/secrets/kipnerter-lfm3/rx480.key");
  out.keyStatus = key.isFile() && (key.mode & 0o077) === 0 &&
    key.size >= 16 && key.size <= 2048 ? "ready" : "invalid";
} catch {}
try {
  const list = JSON.parse(process.env.KIPNERTER_LFM3_ENDPOINTS || "[]");
  out.rosterReady = Array.isArray(list) && list.length === 1 &&
    list[0].name === "rx480" &&
    list[0].baseUrl === "http://100.78.106.121:19176" &&
    list[0].model === "lfm3-1.7b-rx480" &&
    list[0].adapter === "openai" &&
    list[0].role === "interactive" &&
    list[0].maxInflight === 1 &&
    list[0].credentialEnv === "KIPNERTER_LFM3_TOKEN_RX480";
} catch {}
process.stdout.write(JSON.stringify(out));
`;

export function inspectPrivateDemoContainer(container = DEMO_CONTAINER, { exec = execFileSync } = {}) {
  if (container !== DEMO_CONTAINER) throw new Error("unexpected demo container");
  try {
    const raw = exec("docker", ["exec", container, "node", "-e", SCRIPT], {
      timeout: 7000, encoding: "utf8", maxBuffer: 1024,
    });
    const meta = JSON.parse(raw);
    if (!meta || !["ready", "missing", "invalid"].includes(meta.keyStatus) ||
      typeof meta.rosterReady !== "boolean" || typeof meta.stage !== "boolean") {
      throw new Error("malformed readiness metadata");
    }
    return { keyStatus: meta.keyStatus, rosterReady: meta.rosterReady, stage: meta.stage };
  } catch {
    return { keyStatus: "unknown", rosterReady: false, stage: false };
  }
}
const safeMeta = meta => ({
  keyStatus: ["ready", "missing", "invalid"].includes(meta?.keyStatus)
    ? meta.keyStatus : "unknown",
  rosterReady: meta?.rosterReady === true,
  stage: meta?.stage === true,
});

export async function runPrivateDemoAcceptance({
  url = DEMO_URL, inspect = inspectPrivateDemoContainer, fetchImpl = fetch,
} = {}) {
  // This gate must never be usable for public cutover, arbitrary URLs, or a
  // future general-purpose private SSRF proxy.
  if (url !== DEMO_URL) return { decision: "FAIL", gate: "noncanonical-private-demo-url" };
  let meta;
  try { meta = safeMeta(await inspect()); }
  catch { meta = safeMeta(null); }
  if (meta.keyStatus !== "ready" || !meta.rosterReady || !meta.stage) {
    return { decision: "HOLD", gate: "single-worker-private-demo-prerequisites", ...meta };
  }
  try {
    for (const route of ["/", "/chat"]) {
      const res = await fetchImpl(DEMO_URL + route, {
        method: "GET", redirect: "error", cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      const body = await res.text();
      if (res.status !== 200 || body.length > 250000 ||
        !body.includes("Message Kipnerter") || !body.includes("LFM3-1.7B")) {
        return { decision: "FAIL", gate: "demo-ui-route", route, httpStatus: res.status };
      }
    }
    const post = async message => fetchImpl(DEMO_URL + "/api/chat/completions", {
      method: "POST", redirect: "error", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: message }] }),
      signal: AbortSignal.timeout(40000),
    });
    const reject = await post("x".repeat(2000));
    if (reject.status !== 413) {
      return { decision: "FAIL", gate: "pre-inference-size-rejection", httpStatus: reject.status };
    }
    const start = Date.now();
    const completion = await post("What is 2 + 2? Respond with the single digit 4.");
    if (completion.status !== 200) {
      return { decision: "HOLD", gate: "private-rx480-generation", httpStatus: completion.status };
    }
    const bytes = await completion.text();
    if (bytes.length > 32000) return { decision: "FAIL", gate: "response-size" };
    const value = JSON.parse(bytes);
    if (value?.model !== DEMO_MODEL || typeof value.reply !== "string" ||
      !/\b4\b/.test(value.reply)) {
      return { decision: "FAIL", gate: "wrong-model-or-reply" };
    }
    return {
      decision: "DEMO_PASS",
      scope: "single-worker-loopback-only",
      gate: "rx480-authenticated-private-demo",
      model: DEMO_MODEL,
      elapsedMs: Date.now() - start,
    };
  } catch {
    return { decision: "HOLD", gate: "private-demo-network-or-runtime" };
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const result = await runPrivateDemoAcceptance();
  process.stdout.write(JSON.stringify(result) + "\n");
  process.exitCode = result.decision === "DEMO_PASS" ? 0 : result.decision === "HOLD" ? 3 : 2;
}
