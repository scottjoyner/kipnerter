/** Deterministic local summaries of already-authenticated, sanitized telemetry.
 * No model transport, commands, arbitrary hosts, or raw trace payloads.
 */
const MUTATIONS = /\b(?:restart|reboot|shutdown|stop|kill|delete|remove|deploy|ssh|sudo|shell|execute|exec|install|uninstall|load|unload|dispatch|admit|rotate|write|modify|terminate|run|scale|configure|provision|wipe|format)\b/i;
const LABELS = { assistx: "Auto-AssistX", sophia: "Sophia", hermes: "Hermes", opencode: "OpenCode", lmstudio: "Inference", "fleet-monitor": "Tailscale monitoring" };
const list = value => Array.isArray(value) ? value.slice(0, 100) : [];
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
  const match = nodes.find(row => {
    const host = typeof row.name === "string" ? row.name.toLowerCase() : "";
    return host.length > 1 && (q.includes(host) || q.includes(host.split(".")[0]));
  });
  if (nodeIntent || match) {
    if (match) {
      const presence = match.tailscale_online === true ? "reported online" : match.tailscale_online === false ? "reported offline" : "unverified";
      return cap(clean(match.name) + ": Tailscale presence " + presence + "; inflight tasks " + (Number.isInteger(match.inflight) ? match.inflight : "unknown") + ". This does not verify service reachability or authorize execution." + observed);
    }
    if (snapshot.nodes?.status === "unavailable") return "The node inventory source is unavailable. No nodes can be classified as online or offline." + observed;
    const online = nodes.filter(row => row.tailscale_online === true).length;
    const offline = nodes.filter(row => row.tailscale_online === false).length;
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
