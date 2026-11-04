// Server-only LFM3 fleet routing. Never import this module into a client component.
// This module never auto-loads models, authorizes tools, or accepts client-provided URLs.
import { boundedJson } from "./stream-utils.mjs";

const MODEL_ID = /(?:^|[\/_-])lfm3[-_]?1[._-]?7b(?:$|[\/_-])/i;
const active = new Map();
const blockedUntil = new Map();
let roundRobinCursor = 0;
const SYSTEM_PROMPT = "You are Kipnerter, a helpful conversational assistant. Answer clearly and accurately. You cannot execute tools, browse private data, or act on the user's fleet through this public chat. Do not claim tool access.";
export const DISPLAY_MODEL = "LFM3-1.7B";

function privateHost(host) {
  const name = host.toLowerCase();
  if (/^[a-z0-9-]{1,63}$/.test(name) || name.endsWith(".ts.net")) return true;
  const parts = name.split(".");
  if (parts.length !== 4 || !parts.every(x => /^\d{1,3}$/.test(x) && +x <= 255)) return false;
  const [a, b] = parts.map(Number);
  return a === 10 || a === 127 || (a === 192 && b === 168) ||
    (a === 172 && b >= 16 && b <= 31) || (a === 100 && b >= 64 && b <= 127);
}
export function endpointConfig(raw) {
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed) || parsed.length > 16) throw new Error("invalid endpoint configuration");
  const names = new Set();
  return parsed.map(row => {
    if (!row || typeof row !== "object" || Array.isArray(row)) throw new Error("invalid endpoint");
    const { name, baseUrl, model, adapter = "lmstudio", maxInflight = 1, credentialEnv = null } = row;
    if (typeof name !== "string" || !/^[a-zA-Z0-9_-]{1,48}$/.test(name) || names.has(name)) throw new Error("invalid node name");
    names.add(name);
    if (typeof baseUrl !== "string" || baseUrl.length > 250) throw new Error("invalid endpoint URL");
    const url = new URL(baseUrl);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search ||
        url.hash || !["", "/"].includes(url.pathname) || !privateHost(url.hostname)) {
      throw new Error("endpoint must be on the private fleet");
    }
    if (typeof model !== "string" || model.length > 128 || !MODEL_ID.test(model)) throw new Error("endpoint must serve LFM3-1.7B");
    if (!["lmstudio", "openai"].includes(adapter) || !Number.isInteger(maxInflight) || maxInflight < 1 || maxInflight > 8) throw new Error("invalid endpoint adapter or limit");
    if (credentialEnv !== null && (typeof credentialEnv !== "string" || !/^KIPNERTER_LFM3_TOKEN_[A-Z0-9_]{1,48}$/.test(credentialEnv))) throw new Error("invalid per-node credential reference");
    return { name, baseUrl: url.origin, model, adapter, maxInflight, credentialEnv };
  });
}

function headers(token) {
  return { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}
function fetchSignal(signal, milliseconds) {
  const timeout = AbortSignal.timeout(milliseconds);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}
export function isLoaded(entry, node) {
  if (!entry || entry.type === "embedding") return false;
  return (entry.key === node.model || entry.id === node.model ||
    (Array.isArray(entry.loaded_instances) && entry.loaded_instances.some(x => x?.id === node.model))) &&
    Array.isArray(entry.loaded_instances) && entry.loaded_instances.length > 0;
}
export async function endpointReady(node, { fetchImpl = fetch, token = "", signal } = {}) {
  const path = node.adapter === "lmstudio" ? "/api/v1/models" : "/v1/models";
  const res = await fetchImpl(node.baseUrl + path, {
    method: "GET", headers: headers(token), signal: fetchSignal(signal, 3000), cache: "no-store",
  });
  const doc = await boundedJson(res, 128000);
  if (node.adapter === "lmstudio") return Array.isArray(doc.models) && doc.models.some(m => isLoaded(m, node));
  // OpenAI-compatible model listings do not prove residency; a successful
  // generation is required before reporting actual inference success.
  return Array.isArray(doc.data) && doc.data.some(m => m?.id === node.model);
}
function orderedNodes(nodes) {
  const now = Date.now();
  const candidates = [...nodes].filter(n => (blockedUntil.get(n.name) || 0) < now &&
    (active.get(n.name) || 0) < n.maxInflight);
  // Keep requests distributed when several eligible nodes have equal load.
  const offset = roundRobinCursor++ % Math.max(1, candidates.length);
  const order = new Map(candidates.map((n, index) => [n.name, (index - offset + candidates.length) % candidates.length]));
  return candidates.sort((a, b) => (active.get(a.name) || 0) / a.maxInflight -
    (active.get(b.name) || 0) / b.maxInflight || order.get(a.name) - order.get(b.name));
}
function reserve(node) {
  if ((active.get(node.name) || 0) >= node.maxInflight) return false;
  active.set(node.name, (active.get(node.name) || 0) + 1);
  return true;
}
function release(node) { active.set(node.name, Math.max(0, (active.get(node.name) || 1) - 1)); }

export function validateMessages(messages) {
  if (!Array.isArray(messages) || !messages.length || messages.length > 12) throw new Error("invalid message count");
  const clean = messages.map(m => {
    if (!m || !["user", "assistant"].includes(m.role) || typeof m.content !== "string" ||
        !m.content.trim() || m.content.length > 4000) throw new Error("invalid message");
    return { role: m.role, content: m.content.trim() };
  });
  if (clean.at(-1).role !== "user") throw new Error("last message must be user");
  return [{ role: "system", content: SYSTEM_PROMPT }, ...clean];
}
export async function completeFleetChat(messages, {
  nodes, fetchImpl = fetch, token = "", resolveToken = null, signal,
} = {}) {
  const payload = validateMessages(messages);
  if (!Array.isArray(nodes) || nodes.length === 0) return { status: 503, error: "LFM3 fleet is not configured." };
  let hadFree = false;
  for (const node of orderedNodes(nodes)) {
    hadFree = true;
    if (!reserve(node)) continue;
    try {
      const nodeToken = resolveToken ? resolveToken(node) : token;
      if (node.credentialEnv && !nodeToken) continue;
      if (!await endpointReady(node, { fetchImpl, token: nodeToken, signal })) {
        blockedUntil.set(node.name, Date.now() + 10000);
        continue;
      }
      const upstream = await fetchImpl(node.baseUrl + "/v1/chat/completions", {
        method: "POST", signal: fetchSignal(signal, 45000),
        headers: { ...headers(nodeToken), "Content-Type": "application/json" },
        body: JSON.stringify({ model: node.model, messages: payload, stream: false, max_tokens: 512, temperature: 0.1, top_k: 50, repeat_penalty: 1.1 }),
        cache: "no-store",
      });
      if (!upstream.ok) {
        blockedUntil.set(node.name, Date.now() + 10000);
        continue;
      }
      const response = await boundedJson(upstream, 128000);
      const content = response?.choices?.[0]?.message?.content;
      if (typeof content !== "string" || !content.trim() || content.length > 16000) {
        blockedUntil.set(node.name, Date.now() + 10000);
        continue;
      }
      return { status: 200, reply: content, model: DISPLAY_MODEL, runtime: node.name };
    } catch (error) {
      if (signal?.aborted) return { status: 499, error: "Request cancelled." };
      blockedUntil.set(node.name, Date.now() + 10000);
      // Network or runtime failures can use another LFM3 node. Never switch model families.
    } finally {
      release(node);
    }
  }
  return { status: 503, error: hadFree ? "No verified LFM3-1.7B fleet runtime responded." : "All configured LFM3 runtimes are busy or unavailable." };
}