// Operator-only, fail-closed production-host staging gate.
//
// Never reads a credential value. Docker returns only lstat-derived
// metadata booleans from inside the private staging container.
// No public Caddy, iOS settings, models, or service state are modified.
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const EXPECTED_MODEL = "LFM3-1.7B";
const WORKERS = ["r9700", "rx480", "optiplex"];
const DOCKER_CHECK = `
const fs = require("node:fs");
const root = "/run/secrets/kipnerter-lfm3";
const result = {};
for (const name of ["r9700", "rx480", "optiplex"]) {
  try {
    const st = fs.lstatSync(root + "/" + name + ".key");
    result[name] = st.isFile() && (st.mode & 0o077) === 0 &&
      st.size >= 16 && st.size <= 2048 ? "ready" : "invalid";
  } catch { result[name] = "missing"; }
}
process.stdout.write(JSON.stringify(result));
`;

export function inspectStagedSecretMounts(container, { exec = execFileSync } = {}) {
  if (typeof container !== "string" ||
      !/^kipnerter-lfm3-stage-[a-f0-9]{7,40}$/.test(container)) {
    throw new Error("invalid staging container identity");
  }
  try {
    const output = exec("docker",
      ["exec", container, "node", "-e", DOCKER_CHECK],
      { encoding: "utf8", timeout: 7000, maxBuffer: 2048 });
    const result = JSON.parse(output);
    if (!result || WORKERS.some(name => !["ready", "missing", "invalid"].includes(result[name]))) {
      throw new Error("invalid secret readiness response");
    }
    return Object.fromEntries(WORKERS.map(name => [name, result[name]]));
  } catch {
    return Object.fromEntries(WORKERS.map(name => [name, "unknown"]));
  }
}

export async function runGatewayAcceptance({
  url, fetchImpl = fetch, inspectSecrets,
} = {}) {
  let origin;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1" ||
        (parsed.pathname !== "/" && parsed.pathname !== "") ||
        parsed.search || parsed.hash || !/^33[0-9]{2}$/.test(parsed.port)) {
      throw new Error("Only a pinned production-host loopback staging endpoint is allowed.");
    }
    origin = parsed.origin;
  } catch {
    return { decision: "FAIL", gate: "invalid-loopback-staging-origin" };
  }
  const post = async (body, timeoutMs) => fetchImpl(origin + "/api/chat/completions", {
    method: "POST", redirect: "error", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: body }] }),
    signal: AbortSignal.timeout(timeoutMs),
  });

  try {
    const home = await fetchImpl(origin + "/", {
      method: "GET", redirect: "error", cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (home.status !== 200) return { decision: "FAIL", gate: "staging-home", httpStatus: home.status };

    // Size rejection must happen *before* model authentication/generation.
    const oversize = await post("x".repeat(2000), 6000);
    if (oversize.status !== 413)
      return { decision: "FAIL", gate: "oversized-prompt", httpStatus: oversize.status };

    // Missing files are a HOLD, not permission to import or copy them.
    // Stop before any model generation to avoid leaking a prompt through a
    // partial or misconfigured key/roster.
    const mounts = await inspectSecrets();
    if (!mounts || WORKERS.some(name => mounts[name] !== "ready")) {
      return {
        decision: "HOLD", gate: "protected-model-secrets",
        workerMounts: Object.fromEntries(WORKERS.map(name => [
          name, ["ready","missing","invalid"].includes(mounts?.[name]) ? mounts[name] : "unknown",
        ])),
      };
    }

    const start = Date.now();
    const response = await post("What is 2 + 2? Answer with the digit 4.", 40000);
    if (response.status !== 200) {
      return { decision: "HOLD", gate: "authenticated-generation", httpStatus: response.status };
    }
    const bytes = await response.text();
    if (bytes.length > 32000) return { decision: "FAIL", gate: "oversized-generation-response" };
    const payload = JSON.parse(bytes);
    const valid = payload?.model === EXPECTED_MODEL &&
      typeof payload.reply === "string" &&
      payload.reply.trim().length > 0 &&
      /\b4\b/.test(payload.reply);
    if (!valid) return { decision: "FAIL", gate: "wrong-model-or-reply" };
    return {
      decision: "PASS", gate: "authenticated-staged-chat",
      model: EXPECTED_MODEL, elapsedMs: Date.now() - start,
      workerMounts: Object.fromEntries(WORKERS.map(name => [name, "ready"])),
    };
  } catch {
    return { decision: "HOLD", gate: "staging-network-or-runtime" };
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const [container, url] = process.argv.slice(2);
  if (!container || !url) {
    process.stderr.write("Usage: node gateway-acceptance.mjs <stage-container> <http://127.0.0.1:33xx>\n");
    process.exitCode = 2;
  } else {
    const result = await runGatewayAcceptance({
      url, inspectSecrets: () => inspectStagedSecretMounts(container),
    });
    process.stdout.write(JSON.stringify(result) + "\n");
    process.exitCode = result.decision === "PASS" ? 0 : result.decision === "HOLD" ? 3 : 2;
  }
}
