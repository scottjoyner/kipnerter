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
    const { name, baseUrl, model, adapter = "lmstudio", maxInflight = 1, credentialEnv = null, role = "interactive", disableThinking = false, maxOutputTokens = null } = row;
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
    if (!["interactive", "overflow"].includes(role)) throw new Error("invalid endpoint role");
    if (typeof disableThinking !== "boolean" || (maxOutputTokens !== null &&
        (!Number.isInteger(maxOutputTokens) || maxOutputTokens < 32 || maxOutputTokens > 512))) throw new Error("invalid generation policy");
    return { name, baseUrl: url.origin, model, adapter, maxInflight, credentialEnv, role, disableThinking, maxOutputTokens };
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
    method: "GET", headers: headers(token), signal: fetchSignal(signal, 3000),
    redirect: "error", cache: "no-store",
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
  return candidates.sort((a, b) => (a.role === "overflow" ? 1 : 0) - (b.role === "overflow" ? 1 : 0) ||
    (active.get(a.name) || 0) / a.maxInflight -
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
  // A dozen individually valid messages can exceed a 1536-token CPU slot.
  // Keep the newest contiguous turns within a conservative UTF-8 byte budget;
  // never silently truncate the latest user prompt.
  const budgetBytes = 5000;
  const recent = [];
  let used = 0;
  for (let i = clean.length - 1; i >= 0; i--) {
    const cost = new TextEncoder().encode(clean[i].content).byteLength + 24;
    if (used + cost > budgetBytes) {
      if (!recent.length) throw new Error("last message exceeds LFM3 context budget");
      break;
    }
    recent.unshift(clean[i]);
    used += cost;
  }
  return [{ role: "system", content: SYSTEM_PROMPT }, ...recent];
}
// Context-bound admission is per worker: CPU overflow has 1536 tokens,
// while the current GPU research lanes use 2048. Byte-based budgets are
// deliberately stricter than either model window to leave space for special
// tokens, chat templates, and response tokens.
export function fitNodeContext(payload, node) {
  const byteCap = node.role === "overflow" ? 900 : 1300;
  const encoder = new TextEncoder();
  let bytes = encoder.encode(payload[0].content).byteLength + 32;
  const selected = [];
  for (let i = payload.length - 1; i >= 1; i--) {
    const cost = encoder.encode(payload[i].content).byteLength + 40;
    if (bytes + cost > byteCap) {
      // Never silently shorten a user's newest message.
      if (!selected.length) return null;
      break;
    }
    selected.unshift(payload[i]);
    bytes += cost;
  }
  return [payload[0], ...selected];
}

export async function completeFleetChat(messages, {
  nodes, fetchImpl = fetch, token = "", resolveToken = null, signal,
} = {}) {
  const payload = validateMessages(messages);
  if (!Array.isArray(nodes) || nodes.length === 0) return { status: 503, error: "LFM3 fleet is not configured." };
  let hadFree = false;
  const itinerary = orderedNodes(nodes);
  const deadlineAt = Date.now() + 43000; // iOS client timeout is 55s; reserve room for network overhead.
  for (const [index, node] of itinerary.entries()) {
    if (Date.now() >= deadlineAt - 1000) break;
    hadFree = true;
    if (!reserve(node)) continue;
    try {
      const nodeToken = resolveToken ? resolveToken(node) : token;
      if (node.credentialEnv && !nodeToken) continue;
      if (!await endpointReady(node, { fetchImpl, token: nodeToken, signal })) {
        blockedUntil.set(node.name, Date.now() + 10000);
        continue;
      }
      const attemptsLeft = itinerary.length - index;
      const attemptMs = Math.min(42000, Math.max(1000,
        Math.floor((deadlineAt - Date.now() - 1000) / attemptsLeft)));
      const fitted = fitNodeContext(payload, node);
      if (!fitted) continue; // This node cannot hold the latest user turn.
      const upstream = await fetchImpl(node.baseUrl + "/v1/chat/completions", {
        method: "POST", signal: fetchSignal(signal, attemptMs),
        // Never follow a model-server redirect to an unapproved host with
        // private fleet payloads or credentials.
        redirect: "error",
        headers: { ...headers(nodeToken), "Content-Type": "application/json" },
        body: JSON.stringify({ model: node.model, messages: fitted, stream: false,
          max_tokens: node.maxOutputTokens ?? (node.role === "overflow" ? 256 : 512),
          temperature: 0.1, top_k: 50, repeat_penalty: 1.1,
          ...(node.disableThinking === true ? { chat_template_kwargs: { enable_thinking: false } } : {}) }),
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
