"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { signOut } from "next-auth/react";

const SERVICE_NAMES = ["assistx", "sophia", "hermes", "opencode", "tailscale", "traces", "lmstudio"];
const displayNames = { assistx: "Auto-Assist / AssistX", sophia: "Sophia", hermes: "Hermes", opencode: "OpenCode", tailscale: "Tailscale", traces: "Live traces", lmstudio: "Model runtime" };

async function requestJson(url, options) {
  const r = await fetch(url, { cache: "no-store", ...options });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || data.detail || `HTTP ${r.status}`);
  return data;
}

export default function FleetConsole({ user, chatEnabled }) {
  const [view, setView] = useState("chat");
  const [health, setHealth] = useState([]);
  const [observed, setObserved] = useState(null);
  const [models, setModels] = useState([]);
  const [model, setModel] = useState("");
  const [nodes, setNodes] = useState([]);
  const [nodesError, setNodesError] = useState("");
  const [chat, setChat] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [traceId, setTraceId] = useState("");
  const [trace, setTrace] = useState(null);
  const [traceError, setTraceError] = useState("");
  const [traceBusy, setTraceBusy] = useState(false);
  const scrollRef = useRef(null);

  const refresh = useCallback(async () => {
    const [status, inventory, fleet] = await Promise.allSettled([
      requestJson("/api/console/status"),
      requestJson("/api/console/models"),
      requestJson("/api/console/nodes")
    ]);
    if (status.status === "fulfilled") {
      setHealth(status.value.services || []);
      setObserved(status.value.observed_at);
    } else setError(status.reason.message);
    if (inventory.status === "fulfilled") {
      const items = (inventory.value.data || []).filter(item => typeof item.id === "string");
      setModels(items);
      setModel(old => items.some(item => item.id === old) ? old : (items[0]?.id || ""));
    }
    if (fleet.status === "fulfilled") {
      setNodes(fleet.value.nodes || []);
      setNodesError(fleet.value.configured ? "" : "Read-only node collector is not configured");
    } else setNodesError(fleet.reason.message);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 20000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat, busy]);

  async function send(e) {
    e.preventDefault();
    const text = draft.trim();
    if (!chatEnabled || !text || !model || busy) return;
    const messages = [...chat, { role: "user", content: text }].slice(-24);
    setDraft("");
    setChat(messages);
    setBusy(true);
    setError("");
    try {
      const result = await requestJson("/api/console/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model, messages })
      });
      const answer = result?.choices?.[0]?.message?.content;
      if (typeof answer !== "string") throw new Error("Runtime returned no text");
      setChat(current => [...current, { role: "assistant", content: answer }]);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const lookupTrace = useCallback(async () => {
    const id = traceId.trim();
    if (!/^[a-zA-Z0-9_-]{8,96}$/.test(id)) {
      setTraceError("Enter a valid correlation ID (8–96 letters, numbers, _ or -)");
      return;
    }
    setTraceBusy(true);
    setTraceError("");
    try { setTrace(await requestJson(`/api/console/traces?id=${encodeURIComponent(id)}`)); }
    catch (e) { setTrace(null); setTraceError(e.message); }
    finally { setTraceBusy(false); }
  }, [traceId]);

  useEffect(() => {
    if (view !== "traces" || !traceId || !trace) return;
    const timer = setInterval(lookupTrace, 10000);
    return () => clearInterval(timer);
  }, [view, traceId, trace, lookupTrace]);

  const serviceStates = Object.fromEntries(health.map(s => [s.id, s.state]));
  return (
    <div className="fleet-shell">
      <aside className="fleet-sidebar">
        <a className="fleet-brand" href="/"><span className="brand-icon">K</span><span>KIPNERTER<small>FLEET CONSOLE</small></span></a>
        <div className="side-group-title">WORKSPACE</div>
        { [["chat", "◈", "Chat"], ["fleet", "▦", "Fleet overview"], ["traces", "⌁", "Live traces"]].map(([key, icon, title]) =>
          <button key={key} className={`side-nav ${view === key ? "selected" : ""}`} onClick={() => setView(key)}><span className="nav-icon">{icon}</span>{title}</button>
        )}
        <div className="side-group-title space-top">CONNECTED SYSTEMS</div>
        <div className="side-services">
          {SERVICE_NAMES.map(name =>
            <div className="side-service" key={name}>
              <span className={`status-dot ${serviceStates[name] === "responding" ? "is-online" : ""}`} />
              <span>{displayNames[name]}</span>
              <span className="side-state">{serviceStates[name] === "responding" ? "Up" : "—"}</span>
            </div>
          )}
        </div>
        <div className="sidebar-bottom"><span className="user-avatar">{user.charAt(0).toUpperCase()}</span><span className="user-email" title={user}>{user}</span><button className="tiny-button" onClick={() => signOut({ callbackUrl: "/chat" })}>Sign out</button></div>
      </aside>
      <main className="fleet-main">
        <header className="fleet-topbar">
          <div><span className="breadcrumb">KIPNERTER</span><span className="breadcrumb-sep"> / </span><span>{view === "chat" ? "Chat" : view === "fleet" ? "Fleet overview" : "Live traces"}</span></div>
          <div className="topbar-actions"><span className="pill">Private · Authenticated</span><button className="icon-button" title="Refresh inventory" onClick={refresh}>↻</button></div>
        </header>
        {view === "chat" && <section className="conversation">
          <div className="conversation-bar"><div><strong>Conversation</strong><small>Models admitted by your configured inference gateway</small></div><select aria-label="Chat model" value={model} onChange={e => setModel(e.target.value)}><option value="">No model available</option>{models.map(m => <option key={m.id} value={m.id}>{m.id}</option>)}</select></div>
          <div className="message-scroll">
            {chat.length === 0 && <div className="empty-chat"><div className="splash-symbol">✳</div><h1>What are we building?</h1><p>One place to work with your private AI infrastructure. Select a live model above to begin.</p><div className="quick-prompts">{["Summarize the latest fleet changes", "Design an agent workflow", "Help debug an integration"].map(v => <button key={v} onClick={() => setDraft(v)}>{v} ↗</button>)}</div></div>}
            {chat.map((m, i) => <article className={`chat-message ${m.role}`} key={i}><div className="message-avatar">{m.role === "user" ? "YOU" : "K"}</div><div><small>{m.role === "user" ? "You" : model || "Assistant"}</small><p>{m.content}</p></div></article>)}
            {busy && <div className="working-message">● Generating response…</div>}
            <div ref={scrollRef} />
          </div>
          <div className="composer-wrap">{error && <p className="error-line" role="alert">{error}</p>}<form onSubmit={send} className="composer"><textarea aria-label="Your message" value={draft} onChange={e => setDraft(e.target.value)} placeholder={model ? "Message the fleet…" : "Waiting for a verified model…"} rows={2} maxLength={6000} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} /><button type="submit" disabled={!chatEnabled || !model || busy || !draft.trim()}>Send ↑</button></form><p className="composer-note">{chatEnabled ? "Model availability is discovered live. Tools are disabled." : "Chat dispatch is disabled until admission and user-bound execution receipts are verified."}</p></div>
        </section>}
        {view === "fleet" && <section className="fleet-overview"><div className="section-heading"><div><span className="kicker">OPERATIONS</span><h1>Fleet overview</h1><p>Read-only health observations; not proof of model admission or execution readiness.</p></div><button className="subtle-button" onClick={refresh}>Refresh status ↻</button></div><div className="metrics"><div><span>Services responding</span><strong>{health.filter(s => s.state === "responding").length} <em>/ {health.length}</em></strong></div><div><span>Advertised models</span><strong>{models.length}</strong></div><div><span>Visible nodes</span><strong>{nodes.length}</strong></div></div><h2>Connected services</h2><div className="service-grid">{SERVICE_NAMES.map(name => <div className="service-tile" key={name}><div><span className={`status-dot ${serviceStates[name] === "responding" ? "is-online" : ""}`}/><strong>{displayNames[name]}</strong></div><p>{serviceStates[name] || "Unconfigured"}</p></div>)}</div><h2>Tailscale nodes</h2>{nodesError && <p className="muted">{nodesError}</p>}<div className="nodes-grid">{nodes.map(node => <div key={node.name} className="node-card"><span className={`status-dot ${node.online ? "is-online" : ""}`}/><strong>{node.name}</strong><small>{node.online ? "Connected" : "Offline"}</small></div>)}</div><p className="timestamp">Observed {observed ? new Date(observed).toLocaleString() : "not yet"} · refreshes every 20 seconds</p></section>}
        {view === "traces" && <section className="fleet-overview"><div className="section-heading"><div><span className="kicker">OBSERVABILITY</span><h1>Live trace lookup</h1><p>Inspect allowlisted metadata from an exact correlation ID. Prompts, tool arguments, and private payloads are never displayed.</p></div></div><form className="trace-search" onSubmit={e => { e.preventDefault(); lookupTrace(); }}><input aria-label="Trace correlation ID" value={traceId} onChange={e => { setTraceId(e.target.value); setTrace(null); }} placeholder="Correlation / trace ID" maxLength={96}/><button type="submit" disabled={traceBusy}>{traceBusy ? "Loading…" : "Inspect trace"}</button></form>{traceError && <p role="alert" className="error-line">{traceError}</p>}{trace && <div className="trace-timeline"><p className="muted">Trace {trace.trace_id} · refreshes every 10 seconds</p>{trace.events?.length ? trace.events.map((event, i) => <article className="trace-event" key={i}><span className="trace-index">{i + 1}</span><pre>{JSON.stringify(event, null, 2)}</pre></article>) : <p className="muted">No allowlisted events in this trace.</p>}{trace.truncated && <p className="muted">Results capped at 100 events.</p>}</div>}</section>}
      </main>
    </div>
  );
}
