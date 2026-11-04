"use client";
import { useRef, useState } from "react";

export default function HomeChat() {
  const [history, setHistory] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef(null);
  async function submit(event) {
    event.preventDefault();
    if (!draft.trim() || busy) return;
    const next = [...history, { role: "user", content: draft.trim() }].slice(-12);
    setHistory(next);
    setDraft("");
    setBusy(true);
    setError("");
    controller.current = new AbortController();
    try {
      const response = await fetch("/api/chat/completions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: next }), signal: controller.current.signal,
        cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok || typeof result.reply !== "string") throw new Error(result.error || "Chat is unavailable.");
      setHistory(previous => [...previous, { role: "assistant", content: result.reply }].slice(-12));
    } catch (reason) {
      if (reason.name !== "AbortError") setError(reason.message || "Chat is unavailable.");
    } finally {
      controller.current = null;
      setBusy(false);
    }
  }
  function clear() {
    controller.current?.abort();
    setHistory([]);
    setError("");
  }
  return <main className="public-chat">
    <header className="public-chat-header">
      <a className="public-chat-brand" href="/">K<span>·</span> KIPNERTER</a>
      <nav aria-label="Kipnerter navigation">
        <a href="/chat">Private fleet console</a>
      </nav>
    </header>
    <section className="public-chat-main" aria-label="LFM3 conversation">
      {history.length === 0 ? <div className="public-chat-welcome">
        <div className="public-chat-symbol">K</div>
        <p className="eyebrow">FLEET-POWERED CONVERSATION</p>
        <h1>What can I help with?</h1>
        <p>Chat with LFM3-1.7B on the Kipnerter fleet. Requests stay on the same model family even when another node responds.</p>
      </div> : <div className="public-chat-history" aria-live="polite">
        {history.map((message, index) => <div className={`public-chat-bubble ${message.role}`} key={index}>
          <strong>{message.role === "user" ? "You" : "Kipnerter · LFM3"}</strong>
          <p>{message.content}</p>
        </div>)}
      </div>}
      <div className="public-chat-bottom">
        {busy && <p className="public-chat-feedback" role="status">LFM3 is thinking…</p>}
        {error && <p className="public-chat-error" role="alert">{error} Your last message remains in the conversation; retry when ready.</p>}
        <form className="public-chat-form" onSubmit={submit}>
          <label className="public-chat-hidden" htmlFor="public-chat-input">Message Kipnerter</label>
          <textarea id="public-chat-input" rows={3} maxLength={4000} placeholder="Message Kipnerter…"
            value={draft} onChange={event => setDraft(event.target.value)} disabled={busy}
            onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
          <div className="public-chat-actions">
            <span>LFM3-1.7B · Fleet default</span>
            <button type="button" onClick={clear} disabled={!history.length && !busy}>New chat</button>
            <button className="public-chat-submit" type="submit" disabled={!draft.trim() || busy}>Send →</button>
          </div>
        </form>
        <p className="public-chat-note">Messages are sent to a private fleet model for processing. Avoid sharing secrets. Agent tools are not enabled in public chat.</p>
      </div>
    </section>
  </main>;
}
