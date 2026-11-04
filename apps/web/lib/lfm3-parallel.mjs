// Model-only bounded fan-out for a *trusted*, authenticated orchestrator.
// Not imported by anonymous home chat and never performs tool execution.
import { completeFleetChat, DISPLAY_MODEL } from "./lfm3-fleet.mjs";

const limit = (value, maximum) => typeof value === "string" &&
  value.trim().length > 0 && value.length <= maximum;
function physicalHost(node) {
  try { return new URL(node.baseUrl).hostname.toLowerCase(); }
  catch { return null; }
}


export async function runParallelLFM3Research({
  authorized = false, question, subtasks, nodes,
  fetchImpl = fetch, resolveToken = null, signal,
} = {}) {
  if (authorized !== true) return { status: 403, error: "Authenticated research authorization required." };
  if (!limit(question, 700) || !Array.isArray(subtasks) ||
      subtasks.length < 2 || subtasks.length > 3 ||
      !subtasks.every(task => limit(task, 200)) ||
      !Array.isArray(nodes) || nodes.length < subtasks.length) {
    return { status: 400, error: "Requires 2–3 independent bounded tasks and at least two dedicated nodes." };
  }
  // Different aliases, ports, or model instances on the same machine are
  // not independent physical workers. Enforce this before burning tokens.
  const hosts = nodes.map(physicalHost);
  if (hosts.some(host => !host) || new Set(hosts).size < subtasks.length) {
    return { status: 400, error: "Parallel LFM3 research requires distinct physical fleet hosts." };
  }
  const options = { nodes, fetchImpl, resolveToken, signal };
  // Reuses process-local per-node reservations, cooldowns and exact LFM3 checks.
  // No deployment, shells, SensorGraft retrieval, or private fleet mutations.
  const workers = await Promise.all(subtasks.map(subtask => completeFleetChat([
    { role: "user", content: "Question: " + question + "\nAssigned perspective: " + subtask + "\nAnalyze briefly and independently. Do not execute tools or claim external verification." },
  ], options)));
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
  const excerpts = workers.map((worker, i) =>
    "Worker " + (i + 1) + " (" + subtasks[i] + "): " + worker.reply.slice(0, 450));
  const composed = await completeFleetChat([
    { role: "user", content: [
      "Answer this question using the independent LFM3 research summaries. ",
      "Do not claim external verification or tool use. Note uncertainty or disagreement.",
      "\nQuestion: " + question, "\n" + excerpts.join("\n"),
    ].join("") },
  ], options);
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
