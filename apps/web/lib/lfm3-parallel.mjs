// Model-only bounded fan-out for a *trusted*, authenticated orchestrator.
// Not imported by anonymous home chat and never performs tool execution.
import { completeFleetChat, DISPLAY_MODEL, fleetRuntimeSnapshot, fitNodeContext, validateMessages } from "./lfm3-fleet.mjs";

const limit = (value, maximum) => typeof value === "string" &&
  value.trim().length > 0 && value.length <= maximum;
function physicalHost(node) {
  try { return new URL(node.baseUrl).hostname.toLowerCase(); }
  catch { return null; }
}

// Find a complete, distinct-host matching before spending any tokens.
// At most three perspectives and sixteen configured endpoints. Preserve
// the existing GPU-first order whenever a complete matching permits it.
function matchContexts(prompts, candidates) {
  const payloads = prompts.map(validateMessages);
  const used = new Set();
  function search(index) {
    if (index === payloads.length) return [];
    for (const node of candidates) {
      const host = physicalHost(node);
      if (!host || used.has(host) || fitNodeContext(payloads[index], node) === null) continue;
      used.add(host);
      const rest = search(index + 1);
      used.delete(host);
      if (rest !== null) return [node, ...rest];
    }
    return null;
  }
  return search(0);
}

// A response can succeed on every worker but fail during synthesis if 2–3
// long excerpts plus the user question overflow the small local model context.
// Allocate one equal Unicode-safe excerpt budget and check the *actual*
// configured node limits before spending another generation request.
export function fitResearchSynthesis(question, workers, nodes) {
  const prefix = "Answer this question using independent LFM3 summaries. " +
    "Do not claim external verification or tool use. Note uncertainty or disagreement." +
    "\nQuestion: " + question + "\n";
  const excerpts = workers.map(worker => Array.from(worker.reply.trim()));
  const compose = length => prefix + excerpts.map((text, i) =>
    "Worker " + (i + 1) + ": " + text.slice(0, length).join("")).join("\n");
  const fits = text => {
    try {
      const payload = validateMessages([{ role: "user", content: text }]);
      return nodes.some(node => fitNodeContext(payload, node) !== null);
    } catch { return false; }
  };
  // Require enough actual content for each independent perspective, but fail
  // closed rather than publishing an answer based on empty summaries.
  if (!fits(compose(24))) return null;
  let low = 24, high = 450;
  while (low < high) {
    const midpoint = Math.ceil((low + high) / 2);
    if (fits(compose(midpoint))) low = midpoint;
    else high = midpoint - 1;
  }
  return compose(low);
}


export async function runParallelLFM3Research({
  authorized = false, question, subtasks, nodes,
  fetchImpl = fetch, resolveToken = null, signal,
  // Internal-only test override. The HTTP route never passes this from a client.
  timeoutPolicy = { totalMs: 75000, fanoutMs: 40000, spareMs: 14000, synthesisMs: 20000 },
} = {}) {
  if (authorized !== true) return { status: 403, error: "Authenticated research authorization required." };
  if (!limit(question, 700) || !Array.isArray(subtasks) ||
      subtasks.length < 2 || subtasks.length > 3 ||
      !subtasks.every(task => limit(task, 200)) ||
      !Array.isArray(nodes) || nodes.length < subtasks.length || nodes.length > 16) {
    return { status: 400, error: "Requires 2–3 independent bounded tasks and at least two dedicated nodes." };
  }
  // Different aliases, ports, or model instances on the same machine are
  // not independent physical workers. Enforce this before burning tokens.
  const hosts = nodes.map(physicalHost);
  if (hosts.some(host => !host) || new Set(hosts).size < subtasks.length) {
    return { status: 400, error: "Parallel LFM3 research requires distinct physical fleet hosts." };
  }
  // Preflight the smallest useful synthesis before any worker inference.
  // CPU-only rosters have a smaller context window, and an otherwise valid
  // research question may not leave room for independent summaries.
  const baseline = Array.from({ length: subtasks.length }, () => ({
    reply: "A minimum independent model summary.",
  }));
  if (!fitResearchSynthesis(question, baseline, nodes)) {
    return { status: 413, error: "Question and independent LFM3 summaries exceed the available synthesis context." };
  }
  if (signal?.aborted) return { status: 499, error: "Research cancelled." };
  // Keep a single finite end-to-end deadline across fanout, spare recovery
  // and synthesis. The original code could spend 43s on every phase and
  // outlive the web client or reverse-proxy request.
  const bounds = ["totalMs", "fanoutMs", "spareMs", "synthesisMs"];
  if (!timeoutPolicy || bounds.some(key =>
      !Number.isInteger(timeoutPolicy[key]) ||
      timeoutPolicy[key] < 1 || timeoutPolicy[key] > 75000)) {
    throw new Error("invalid internal parallel inference time budget");
  }
  const totalSignal = signal
    ? AbortSignal.any([signal, AbortSignal.timeout(timeoutPolicy.totalMs)])
    : AbortSignal.timeout(timeoutPolicy.totalMs);
  const phaseSignal = milliseconds => AbortSignal.any([
    totalSignal, AbortSignal.timeout(milliseconds),
  ]);
  const stopped = () => signal?.aborted
    ? { status: 499, error: "Research cancelled." }
    : { status: 504, error: "Parallel LFM3 research exceeded its bounded time budget." };
  const options = { fetchImpl, resolveToken };
  // Assign dedicated physical hosts BEFORE parallel work, not after it.
  // Round-robin calls racing for the same global pool could otherwise
  // converge onto one host after a failure and waste the entire fan-out.
  // Preserve interactive GPU priority and use an idle CPU only as overflow.
  const available = nodes.filter(node => {
    const snapshot = fleetRuntimeSnapshot(node);
    return !snapshot.cooldown && snapshot.inFlight < snapshot.maxInflight;
  }).sort((a, b) => Number(a.role === "overflow") - Number(b.role === "overflow"));
  if (!fitResearchSynthesis(question, baseline, available)) {
    return { status: 503, error: "No idle LFM3 runtime fits the minimum synthesis context." };
  }
  if (new Set(available.map(physicalHost)).size < subtasks.length) {
    return { status: 503, error: "Not enough distinct idle LFM3 workers for parallel research." };
  }
  const prompt = task => [{
    role: "user", content: "Question: " + question + "\nAssigned perspective: " + task +
      "\nAnalyze briefly and independently. Do not execute tools or claim external verification.",
  }];
  const prompts = subtasks.map(prompt);
  const assigned = matchContexts(prompts, available);
  if (!assigned) return { status: 413, error: "No distinct idle LFM3 worker assignment fits every perspective." };
  const assignedHosts = new Set(assigned.map(physicalHost));
  const spares = available.filter(node => !assignedHosts.has(physicalHost(node)));
  const workerSignal = phaseSignal(timeoutPolicy.fanoutMs);
  const workers = await Promise.all(subtasks.map((task, index) =>
    completeFleetChat(prompt(task), { ...options, nodes: [assigned[index]], signal: workerSignal })));
  if (workerSignal.aborted) return stopped();

  // Failed perspectives may be retried only on a DISTINCT idle spare, never
  // on a worker another perspective already used. A spare is leased to at
  // most one failed task; no repeated probes or surprise model loading.
  const failed = workers.flatMap((worker, index) =>
    worker.status === 200 ? [] : [index]);
  if (failed.length > new Set(spares.map(physicalHost)).size) {
    return { status: 503, error: "A parallel LFM3 worker was unavailable; no partial synthesis was published." };
  }
  if (totalSignal.aborted) return stopped();
  const spareAssignment = matchContexts(failed.map(index => prompts[index]), spares.filter(node => {
    const snapshot = fleetRuntimeSnapshot(node);
    return !snapshot.cooldown && snapshot.inFlight < snapshot.maxInflight;
  }));
  if (!spareAssignment) return { status: 503, error: "No distinct available spare fits the failed perspectives." };
  const spareSignal = phaseSignal(timeoutPolicy.spareMs);
  const recovered = await Promise.all(failed.map((index, i) =>
    completeFleetChat(prompts[index], { ...options, nodes: [spareAssignment[i]], signal: spareSignal })));
  for (let i = 0; i < failed.length; i++) workers[failed[i]] = recovered[i];
  if (spareSignal.aborted) return stopped();
  if (workers.some(result => result.status !== 200)) {
    return { status: 503, error: "A parallel LFM3 worker was unavailable; no partial synthesis was published." };
  }
  // A simultaneous worker can fail over onto a node that just completed
  // another perspective. Reject duplicate runtime provenance rather than
  // presenting two outputs from one node as independent analyses.
  const physicalRuntimes = workers.map(result => {
    const match = nodes.find(node => node.name === result.runtime);
    return match ? physicalHost(match) : null;
  });
  if (new Set(workers.map(result => result.runtime)).size !== workers.length ||
      physicalRuntimes.some(host => !host) ||
      new Set(physicalRuntimes).size !== workers.length) {
    return { status: 503, error: "Distinct LFM3 workers were not available for independent research." };
  }
  if (!fitResearchSynthesis(question, workers, nodes)) {
    return { status: 413, error: "Question and independent LFM3 summaries exceed the available synthesis context." };
  }
  const synthesisNodes = nodes.filter(node => {
    const snapshot = fleetRuntimeSnapshot(node);
    return !snapshot.cooldown && snapshot.inFlight < snapshot.maxInflight;
  });
  const synthesis = fitResearchSynthesis(question, workers, synthesisNodes);
  if (!synthesis) {
    return { status: 503, error: "No idle LFM3 runtime fits the synthesis context." };
  }
  if (totalSignal.aborted) return stopped();
  const synthesisSignal = phaseSignal(timeoutPolicy.synthesisMs);
  const composed = await completeFleetChat([
    { role: "user", content: synthesis },
  ], { ...options, nodes: synthesisNodes, signal: synthesisSignal });
  if (synthesisSignal.aborted) return stopped();
  if (composed.status !== 200) {
    return { status: 503, error: "LFM3 synthesis unavailable." };
  }
  return {
    status: 200, model: DISPLAY_MODEL,
    reply: composed.reply,
    workerRuntimes: workers.map(result => result.runtime),
    synthesisRuntime: composed.runtime,
  };
}
