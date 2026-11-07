"use client";
import { useRef, useState } from "react";

// Explicit, operator-only model research. No command execution, private data
// retrieval, or automatic fan-out from public / iOS chat.
export default function ParallelResearchPanel() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [error, setError] = useState("");
  const [workers, setWorkers] = useState(null);
  const [checking, setChecking] = useState(false);
  const controller = useRef(null);

  async function inspectFleet() {
    if (checking || busy) return;
    setChecking(true);
    setError("");
    try {
      const response = await fetch("/api/chat/fleet-status", {
        method: "GET", credentials: "same-origin", cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok || !Array.isArray(payload.workers)) {
        throw new Error(payload.error || "Fleet model discovery unavailable.");
      }
      setWorkers(payload.workers);
    } catch (reason) {
      setWorkers(null);
      setError(reason.message || "Fleet model discovery failed.");
    } finally {
      setChecking(false);
    }
  }

  async function research(event) {
    event.preventDefault();
    if (busy || question.trim().length < 4 || question.trim().length > 700) return;
    setBusy(true);
    setAnswer(null);
    setError("");
    const abort = new AbortController();
    controller.current = abort;
    try {
      const response = await fetch("/api/chat/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim() }),
        cache: "no-store",
        credentials: "same-origin",
        signal: abort.signal,
      });
      const body = await response.json();
      if (!response.ok || typeof body.reply !== "string") {
        throw new Error(body.error || "LFM3 parallel research was unavailable.");
      }
      setAnswer(body);
    } catch (reason) {
      if (reason.name !== "AbortError") setError(reason.message || "Parallel research failed.");
    } finally {
      if (controller.current === abort) controller.current = null;
      setBusy(false);
    }
  }
  return <section className="workspace-panel chat-workspace" style={{ marginTop: 20 }} aria-label="Parallel LFM3 model research">
    <div className="panel-heading">
      <div>
        <h2>Parallel LFM3 research</h2>
        <p>Opt-in · two independent fleet-model analyses, followed by synthesis. Requires an authorized operator session.</p>
      </div>
      <span className="state-badge">MODEL ONLY</span>
    </div>
    <div style={{ marginBottom: 14 }}>
      <button type="button" onClick={inspectFleet} disabled={checking || busy}>
        {checking ? "Checking model catalogs…" : "Detect fleet LFM3 workers"}
      </button>
      {workers && <div role="status" aria-live="polite" style={{ marginTop: 9 }}>
        <strong>Configured workers</strong>
        {workers.length === 0 ? <p>No LFM3 workers are configured.</p> : <ul>
          {workers.map(item => <li key={item.name}>
            <strong>{item.name}</strong> · {item.role === "overflow" ? "CPU / overflow" : "Interactive"} · {item.state}
            {item.cooldown ? " · Cooling down after a failure" : ""}
            {" · "}{item.inFlight ?? 0}/{item.maxInflight ?? 1} slots busy
            {Number.isInteger(item.lastLatencyMs) ? " · recent completion " + item.lastLatencyMs + " ms" : ""}
            {item.lastSuccessAt ? " · Served a request in this app process" : ""}
          </li>)}
        </ul>}
        <small>Catalog-listed is not proof of loaded weights or successful generation.</small>
      </div>}
    </div>
    <form onSubmit={research}>
      <label htmlFor="parallel-lfm3-question">Research question</label>
      <textarea id="parallel-lfm3-question" rows={3} maxLength={700} value={question}
        onChange={event => setQuestion(event.target.value)}
        placeholder="What should two independent fleet models evaluate?" disabled={busy} />
      <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
        <button type="submit" className="primary-btn" disabled={busy || question.trim().length < 4}>
          {busy ? "Research running…" : "Run parallel LFM3 research"}
        </button>
        {busy && <button type="button" onClick={() => controller.current?.abort()}>
          Cancel
        </button>}
      </div>
    </form>
    {busy && <p role="status">Independent model-only workers are evaluating the question. No tool calls are authorized.</p>}
    {error && <p role="alert" className="portal-warning">{error}</p>}
    {answer && <div className="fleet-chat-history" role="log" aria-label="Parallel research result">
      <div className="fleet-chat-message answer"><strong>Kipnerter · LFM3 research synthesis</strong>
        <p style={{ whiteSpace: "pre-wrap" }}>{answer.reply}</p>
        <small>Workers: {answer.workerRuntimes?.join(" + ") || "unavailable"} · Synthesis: {answer.synthesisRuntime || "unavailable"}</small>
      </div>
    </div>}
    <p className="fine-print">Outputs are unverified model analysis, not signed fleet traces or evidence of live Hermes agent execution.</p>
  </section>;
}
