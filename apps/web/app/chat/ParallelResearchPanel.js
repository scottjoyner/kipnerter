"use client";
import { useRef, useState } from "react";

// Explicit, operator-only model research. No command execution, private data
// retrieval, or automatic fan-out from public / iOS chat.
export default function ParallelResearchPanel() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [error, setError] = useState("");
  const controller = useRef(null);

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
