// Private server-only credential resolver. Never expose token values to browsers,
// iOS apps, logs, GitHub Actions, or a Docker container's inspected environment.
import { lstatSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SECRET_ROOT = "/run/secrets/kipnerter-lfm3";
const NODE_NAME = /^[a-zA-Z0-9_-]{1,48}$/;
const ENV_NAME = /^KIPNERTER_LFM3_TOKEN_[A-Z0-9_]{1,48}$/;

function validKey(raw) {
  if (typeof raw !== "string") return "";
  const value = raw.trim();
  return value.length >= 16 && value.length <= 1024 &&
    !/\s/.test(value) && !/[^a-zA-Z0-9._~+\/-]/.test(value) ? value : "";
}

function readPrivateKey(path) {
  try {
    // lstat, not stat: refuse symlinked secrets and group/other access.
    const stat = lstatSync(path);
    if (!stat.isFile() || (stat.mode & 0o077) !== 0 ||
        stat.size < 16 || stat.size > 2048) return { present: true, value: "" };
    return { present: true, value: validKey(readFileSync(path, "utf8")) };
  } catch (error) {
    if (error?.code === "ENOENT") return { present: false, value: "" };
    return { present: true, value: "" }; // permissions and I/O errors fail closed
  }
}

// root/env parameters are injectable for isolated tests, not request options.
// A present but invalid secret file cannot be bypassed with a legacy env value.
export function resolveFleetNodeCredential(node, {
  env = process.env, root = SECRET_ROOT,
} = {}) {
  if (!node || !NODE_NAME.test(node.name || "")) return "";
  if (!node.credentialEnv) return validKey(env.KIPNERTER_LFM3_BEARER);
  if (!ENV_NAME.test(node.credentialEnv)) return "";
  const file = readPrivateKey(join(root, node.name + ".key"));
  if (file.present) return file.value;
  return validKey(env[node.credentialEnv]);
}
