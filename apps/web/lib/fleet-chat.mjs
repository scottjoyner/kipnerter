/** Deterministic local summaries of already-authenticated, sanitized telemetry.
 * No model transport, commands, arbitrary hosts, or raw trace payloads.
 */
const MUTATIONS = /\b(?:restart|reboot|shutdown|stop|kill|delete|remove|deploy|ssh|sudo|shell|execute|exec|install|uninstall|load|unload|dispatch|admit|rotate|write|modify|terminate|run|scale|configure|provision|wipe|format)\b/i;
const LABELS = { assistx: "Auto-AssistX", sophia: "Sophia", hermes: "Hermes", opencode: "OpenCode", lmstudio: "Inference", "fleet-monitor": "Tailscale monitoring" };
const list = value => Array.isArray(value) ? value.slice(0, 100).filter(row => row && typeof row === "object" && !Array.isArray(row)) : [];
const escapeRegExp = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const mentionsHost = (question, hostname) => {
  if (typeof hostname !== "string" || hostname.length < 2 || hostname.length > 90) return false;
  const full = hostname.toLowerCase();
  const short = full.split(".")[0];
  return [full, short].some(label => label.length > 1 &&
    new RegExp("(^|[^a-z0-9_-])" + escapeRegExp(label) + "(?=$|[^a-z0-9_-])").test(question));
};
const status = value => typeof value === "string" && value.length <= 40 ? value.replaceAll("_", " ") : "unavailable";
const cap = value => String(value).slice(0, 1800);
const clean = value => typeof value === "string" ? value.replace(/[\r\n\t]+/g, " ").slice(0, 90) : "unknown";
const name = value => LABELS[value] || clean(value);
const stamp = value => typeof value === "string" && !Number.isNaN(Date.parse(value)) ? new Date(value).toISOString() : "unknown";
const any = (q, terms) => terms.some(re => re.test(q));

export function answerFleetQuestion(question, snapshot, { fresh = false, observedAt = "" } = {}) {
  if (typeof question !== "string" || !question.trim() || question.length > 4000) {
    return "Enter a question of 1–4,000 characters about fleet status, nodes, models, agents, sessions, or traces.";
  }
  const q = question.trim().toLowerCase();
  if (MUTATIONS.test(q)) {
    return "This console cannot execute commands, change fleet state, load models, or deploy services. It only summarizes read-only telemetry. Authorized actions require a separate, audited control plane.";
  }
  if (!fresh || !snapshot || typeof snapshot !== "object") {
    return "No fresh authenticated fleet snapshot is available. Status is unknown; reconnect to the private observer before relying on node, model, session, or trace information.";
  }
  const nodes = list(snapshot.nodes?.nodes);
  const models = list(snapshot.models?.models);
  const agents = list(snapshot.overview?.integrations);
  const sessions = list(snapshot.sessions?.sessions);
  const traces = list(snapshot.traces?.traces);
  const observed = observedAt ? " Browser received snapshot at " + clean(observedAt) + "." : "";
  const nodeIntent = any(q, [/\bnode(s)?\b/, /\bfleet\b/, /\bmachine(s)?\b/, /\bcomputer(s)?\b/, /\bonline\b/, /\boffline\b/, /\bhost(s)?\b/]);
  const modelIntent = any(q, [/\bmodel(s)?\b/, /\binference\b/, /\blm studio\b/, /\bloaded\b/, /\bruntime\b/]);
  const tracesIntent = any(q, [/\btrace(s)?\b/, /\bevent(s)?\b/, /\bactivity\b/, /\bobservability\b/]);
  const sessionsIntent = any(q, [/\bsession(s)?\b/, /\bjob(s)?\b/, /\bhermes\b/, /\bopencode\b/]);
  const healthIntent = any(q, [/\bhealth\b/, /\bhealthy\b/, /\bservice(s)?\b/, /\bintegration(s)?\b/, /\bstatus\b/, /\bassistx\b/, /\bsophia\b/]);
  // Prefer the longest exact host token. A substring in an unrelated name
  // must never become a reported physical host observation.
  const match = [...nodes].filter(row => typeof row.name === "string")
    .sort((a, b) => b.name.length - a.name.length)
    .find(row => mentionsHost(q, row.name));
  const needsNodeInventory = Boolean(match) || (nodeIntent && !modelIntent && !sessionsIntent && !tracesIntent);
  if (needsNodeInventory && snapshot.nodes?.status === "unavailable") {
    return "The node inventory source is unavailable. No nodes can be classified as online or offline." + observed;
  }
  if (match && (sessionsIntent || tracesIntent)) {
    return cap(clean(match.name) + ": node-specific session and trace attribution is unverified. The portal does not independently join launcher receipts or AssistX traces to this host." + observed);
  }
  if (match && modelIntent) {
    const reported = Array.isArray(match.models)
      ? match.models.slice(0, 16).filter(value => typeof value === "string" && value.trim()).map(clean)
      : null;
    if (!reported) return cap(clean(match.name) + ": model membership is unavailable in this node observation. No model loading or residency is verified." + observed);
    return cap(clean(match.name) + ": " + reported.length + " reported node model labels" +
      (reported.length ? ": " + reported.slice(0, 8).join(", ") : ".") +
      (reported.length > 8 ? " (additional labels omitted)." : ".") +
      " These are inventory labels, not verified loaded instances, inference readiness, or AssistX admission." + observed);
  }
  if (needsNodeInventory) {
    if (match) {
      const presence = match.tailscale_online === true ? "reported online" : match.tailscale_online === false ? "reported offline" : "unverified";
      return cap(clean(match.name) + ": Tailscale presence " + presence + "; inflight tasks " + (Number.isInteger(match.inflight) ? match.inflight : "unknown") + ". This does not verify service reachability or authorize execution." + observed);
    }
    const online = nodes.filter(row => row.tailscale_online === true).length;
    const offline = nodes.filter(row => row.tailscale_online === false).length;
    const listNames = /\b(which|list|show|name|identify)\b/.test(q);
    const offlineOnly = /\boffline\b/.test(q) && !/\bonline\b/.test(q);
    const onlineOnly = /\bonline\b/.test(q) && !/\boffline\b/.test(q);
    if (listNames && (offlineOnly || onlineOnly)) {
      const matching = nodes.filter(row => row.tailscale_online === (onlineOnly ? true : false));
      const labels = matching.slice(0, 8).map(row => clean(row.name)).join(", ");
      return cap("Tailscale observer reports " + nodes.length + " nodes: " + online +
        " online, " + offline + " offline, " + (nodes.length - online - offline) +
        " unverified. " + (onlineOnly ? "Reported online: " : "Reported offline: ") +
        (labels || "none explicitly reported") +
        (matching.length > 8 ? " (additional names omitted)." : ".") +
        " Presence does not verify service or model readiness." + observed);
    }
    return cap("Tailscale observer reports " + nodes.length + " nodes: " + online + " online, " + offline + " offline, " + (nodes.length - online - offline) + " unverified. Presence is not endpoint or model readiness." + observed);
  }
  if (modelIntent) {
    if (snapshot.models?.status === "unavailable") return "Model catalog sources are unavailable; loaded state and admission are unknown." + observed;
    const sources = [...new Set(models.map(row => clean(row.source)))];
    const loaded = models.reduce((count, row) => count + (row.source === "lmstudio_native_catalog" && Number.isSafeInteger(row.loaded_instances) && row.loaded_instances >= 0 ? row.loaded_instances : 0), 0);
    return cap(models.length + " catalog entries reported" + (sources.length ? " by " + sources.join(", ") : "") + ". Native LM Studio instances reported loaded: " + loaded + ". Neither catalog presence nor runtime-reported loading proves model residency, AssistX admission, or inference availability." + observed);
  }
  if (tracesIntent) {
    if (snapshot.traces?.status === "unavailable") return "Trace index unavailable; no live execution can be inferred." + observed;
    return cap(traces.length + " sanitized AssistX trace-index entries; source state: " + status(snapshot.traces?.status) + "; latest source event: " + stamp(snapshot.traces?.last_event_at) + ". The feed excludes prompts and payloads. Polling freshness is not evidence of new execution." + observed);
  }
  if (sessionsIntent) {
    if (snapshot.sessions?.status === "unavailable") return "Agent-session receipts unavailable. Agent execution is not verified." + observed;
    const recent = sessions.slice(0, 4).map(row => name(row.agent) + " " + clean(row.id) + " (" + status(row.status) + ")").join("; ");
    return cap(sessions.length + " launcher session receipts" + (recent ? ": " + recent : ".") + ". Requested models, archival state, and job receipts are not independent execution attestations." + observed);
  }
  if (healthIntent) {
    if (snapshot.overview?.status === "unavailable") return "Service-health projections unavailable; no integration can be classified as healthy." + observed;
    const summary = agents.slice(0, 8).map(row => name(row.id) + ": " + status(row.status)).join("; ");
    return cap("Integration probes (not admission or dispatch proof): " + (summary || "no available reports") + "." + observed);
  }
  return "I can answer read-only questions such as: Which fleet nodes are online? What models are listed? Are any AssistX traces live? What Hermes sessions are reported? How are the integrations doing? No model inference or remote commands are enabled.";
}
