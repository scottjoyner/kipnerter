"use client";
import { useEffect, useState } from "react";
import { snapshotExpired, canApplyPoll } from "../../lib/telemetry-freshness.mjs";

const SECTIONS = [
  { id: "chat", icon: "◈", label: "Chat" },
  { id: "agents", icon: "◇", label: "Agents" },
  { id: "models", icon: "⬡", label: "Models" },
  { id: "nodes", icon: "▦", label: "Fleet nodes" },
  { id: "traces", icon: "≋", label: "Live traces" },
];
const LABELS = {
  assistx: "Auto-AssistX", sophia: "Sophia", hermes: "Hermes",
  opencode: "OpenCode", "fleet-monitor": "Tailscale monitoring", lmstudio: "Inference",
};
const noData = { integrations: [], models: [], nodes: [], traces: [], sessions: [] };
function human(value) { return LABELS[value] || value; }
function Badge({ status }) {
  return <span className={`state-badge ${["healthy", "live", "reported"].includes(status) ? "state-ok" : ""}`}>
    <span className="state-dot" />{status?.replaceAll("_", " ") || "unavailable"}
  </span>;
}
function Empty({ title, detail }) {
  return <div className="empty-state"><div className="empty-icon">⌁</div><h3>{title}</h3><p>{detail}</p></div>;
}
export default function FleetConsole({ email }) {
  const [tab, setTab] = useState("chat");
  const [data, setData] = useState({});
  const [errors, setErrors] = useState({});
  const [updated, setUpdated] = useState(null);
  const [connection, setConnection] = useState("connecting");
  useEffect(() => {
    let stopped = false;
    let lastReceivedAt = 0;
    let generation = 0;
    async function refresh() {
      const ticket = ++generation;
      const results = await Promise.all(["overview", "models", "nodes", "traces", "sessions"].map(async key => {
        try {
          const response = await fetch(`/api/portal/${key}`, { cache: "no-store" });
          if (!response.ok) throw Error(`HTTP ${response.status}`);
          return [key, await response.json(), null];
        } catch (error) { return [key, null, error.message]; }
      }));
      if (canApplyPoll(ticket, generation, stopped)) {
        const success = results.some(row => row[1] !== null);
        setData(success
          ? Object.fromEntries(results.map(([key, value]) => [key, value || { ...noData, status: "unavailable" }]))
          : {});
        setErrors(Object.fromEntries(results.filter(row => row[2]).map(row => [row[0], row[2]])));
        lastReceivedAt = success ? Date.now() : 0;
        setUpdated(success ? new Date().toLocaleTimeString() : null);
        setConnection(success ? "polling fallback" : "unavailable");
      }
    }
    refresh();
    let streaming = false;
    const events = new EventSource("/api/portal/live");
    events.addEventListener("snapshot", message => {
      if (stopped) return;
      try {
        const next = JSON.parse(message.data);
        if (!next || typeof next !== "object" || Array.isArray(next)) return;
        ++generation;
        setData(next);
        setErrors({});
        lastReceivedAt = Date.now();
        setUpdated(new Date().toLocaleTimeString());
        setConnection("live stream");
        streaming = true;
      } catch { /* preserve the last valid state until the fallback refresh */ }
    });
    events.onerror = () => {
      streaming = false;
      setConnection("reconnecting");
    };
    const timer = setInterval(() => { if (!streaming) refresh(); }, 30000);
    const expiry = setInterval(() => {
      if (snapshotExpired(lastReceivedAt, Date.now())) {
        lastReceivedAt = 0;
        streaming = false;
        ++generation;
        // Clear the old green badges and observations immediately, even if
        // an upstream SSE reconnect or fallback request is still outstanding.
        setData({});
        setUpdated(null);
        setConnection("stale");
      }
    }, 5000);
    return () => {
      stopped = true;
      ++generation;
      events.close();
      clearInterval(timer);
      clearInterval(expiry);
    };
  }, []);
  const integrations = data.overview?.integrations || [];
  const models = data.models?.models || [];
  const nodes = data.nodes?.nodes || [];
  const traces = data.traces?.traces || [];
  const sessions = data.sessions?.sessions || [];
  const healthy = integrations.filter(s => s.status === "healthy").length;
  // These are observations from distinct systems, not a cryptographic trace join.
  const timeline = [
    ...traces.map(trace => ({
      key: "assistx:" + trace.correlation_id, kind: "AssistX trace", id: trace.correlation_id,
      status: trace.outcome, count: trace.events, duration_ms: trace.duration_ms,
      time: Number(trace.last_ts_ms) || 0, verified: true,
    })),
    ...sessions.map(job => ({
      key: "launcher:" + job.id, kind: human(job.agent) + " job", id: job.id,
      status: job.status.toLowerCase(), model: job.model,
      time: Date.parse(job.created_utc) || 0, verified: false,
      hold: job.harvest_hold,
    })),
  ].sort((a, b) => b.time - a.time).slice(0, 50);
  return <div className="portal">
    <aside className="portal-sidebar">
      <a className="portal-logo" href="/">K<span>·</span><span className="portal-logo-text">KIPNERTER<small>UNIFIED FLEET</small></span></a>
      <div className="sidebar-caption">WORKSPACE</div>
      <nav aria-label="Fleet workspace">
        {SECTIONS.map(item => <button key={item.id} type="button"
          className={`nav-entry ${tab === item.id ? "selected" : ""}`}
          onClick={() => setTab(item.id)}><span className="nav-symbol">{item.icon}</span>{item.label}</button>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-status"><span className="pulse" />Private fleet · authenticated</div>
        <div className="sidebar-identity"><span className="avatar">{email[0]?.toUpperCase()}</span>
          <span className="identity-name">{email}<small>Authorized operator</small></span></div>
        <a className="signout-link" href="/api/auth/signout?callbackUrl=%2Fchat">Sign out ↗</a>
      </div>
    </aside>
    <main className="portal-main">
      <header className="portal-header">
        <div className="header-breadcrumb">KIPNERTER <span>/</span> {SECTIONS.find(s => s.id === tab)?.label.toUpperCase()}</div>
        <div className="header-tools"><span className="read-only">READ ONLY CONTROL PLANE</span><span>{connection} · {updated ? `Observed ${updated}` : "No fresh observation"}</span></div>
      </header>
      <div className="portal-content">
        {tab === "chat" && <>
          <div className="page-intro"><p className="section-kicker">YOUR AI WORKSPACE</p>
            <h1>One fleet. One interface<span className="accent">.</span></h1>
            <p>Route conversations and inspect agents across your private compute infrastructure.</p></div>
          <div className="stat-grid">
            <div className="stat-card"><span>Service probes</span><strong>{healthy}<small> / {integrations.length || 6}</small></strong><p>Healthy integrations</p></div>
            <div className="stat-card"><span>Reported models</span><strong>{models.length}</strong><p>Catalog entries; admission unverified</p></div>
            <div className="stat-card"><span>Fleet inventory</span><strong>{nodes.length}</strong><p>Tailscale presence verified only by the private observer</p></div>
          </div>
          <section className="workspace-panel chat-workspace">
            <div className="panel-heading"><div><h2>New conversation</h2><p>Model routing is held until authenticated admission and receipt validation are connected.</p></div><Badge status="not_configured" /></div>
            <div className="chat-welcome"><div className="chat-mark">✳</div><h3>What should we work on?</h3><p>Auto-AssistX, Sophia, Hermes, and OpenCode will share one conversation history and trace lineage.</p></div>
            <div className="composer-locked"><span>◈</span><span>Chat execution is disabled until the router admission gate passes.</span><span>↵</span></div>
          </section>
        </>}
        {tab === "agents" && <>
          <div className="page-intro"><p className="section-kicker">AGENT ORCHESTRATION</p><h1>Agents<span className="accent">.</span></h1><p>Service health signals only. Execution requires a separately authorized workflow.</p></div>
          <section className="integration-grid">{integrations.filter(s => ["assistx", "sophia", "hermes", "opencode"].includes(s.id)).map(s =>
            <div key={s.id} className="integration-card"><div className="integration-icon">{human(s.id).slice(0, 1)}</div><h3>{human(s.id)}</h3><Badge status={s.status}/><p>{s.source === "x1_observer" && s.status === "healthy" ? "Healthy on x1-370 · production routing unverified" :
              s.source === "x1_observer" ? "Local observation only · worker readiness unverified" :
              s.source === "production_upstream_probe" ? "Probed from production API" :
              "No verified response"}{s.latency_ms == null ? "" : ` · ${s.latency_ms} ms`}</p></div>)}</section>
          <section className="workspace-panel" style={{marginTop:20}}>
            <div className="panel-heading"><div><h2>Hermes & OpenCode sessions</h2><p>Read-only launcher receipts. Requested models are not execution attestations.
              {data.sessions?.observer_observed_at ? " · Observed " + new Date(data.sessions.observer_observed_at).toLocaleTimeString() : ""}</p></div><Badge status={data.sessions?.status || "unavailable"}/></div>
            {sessions.length ? <div className="data-list">{sessions.map(job => <div key={job.id} className="data-row">
              <div><span className="row-main">{human(job.agent)} · {job.id}</span>
              <small>{job.model} · {job.created_utc ? new Date(job.created_utc).toLocaleString() : "unknown start"}</small>
              <small>{job.harvest_hold ? "Archive security hold" : job.archive_verified ? "Archive verified" : "Archive not verified"} · {job.model_verified ? "Model verified" : "Model not independently verified"}</small></div><Badge status={job.status?.toLowerCase()}/></div>)}</div> :
              <Empty title="No verified agent sessions" detail="Requires an authenticated fleet observer connected to the launcher ledger; sessions are never fabricated."/>}
          </section>
        </>}
        {tab === "models" && <>
          <div className="page-intro"><p className="section-kicker">INFERENCE REGISTRY</p><h1>Models<span className="accent">.</span></h1><p>Independent LM Studio catalog and AssistX registry. A reported loaded instance is not an independent residency or admission attestation.</p></div>
          <section className="workspace-panel"><div className="panel-heading"><h2>Reported inventory</h2><Badge status={data.models?.status || "unavailable"}/></div>
            {models.length ? <div className="data-list">{models.map(model => <div className="data-row" key={model.id}><div><span className="row-main">{model.name || model.id}</span><small>{model.source === "lmstudio_native_catalog" ? "LM Studio local catalog" : "AssistX registry"} · {model.independently_verified ? "verified" : "not independently verified"}</small></div><span>{model.source === "lmstudio_native_catalog" ? (model.loaded_instances ?? 0) + " runtime-reported instances" : model.nodes + " AssistX reported nodes"}</span></div>)}</div> :
              <Empty title={data.models?.status === "reported_empty" ?
                "AssistX reports no registered models" : "No verified model inventory"}
                detail={data.models?.status === "reported_empty" ?
                "The private AssistX inventory endpoint returned an empty catalog. Tailscale presence does not prove model loading; provider discovery needs separate validation." :
                "The fresh private AssistX inventory feed is unavailable. Credentials are never exposed to this portal."}/>}</section>
        </>}
        {tab === "nodes" && <>
          <div className="page-intro"><p className="section-kicker">TAILNET & COMPUTE</p><h1>Fleet nodes<span className="accent">.</span></h1><p>AssistX node inventory is shown separately from Tailscale connectivity verification.</p></div>
          <section className="workspace-panel"><div className="panel-heading"><div><h2>Fleet inventory</h2><p>{data.nodes?.observer_observed_at ?
              "Tailscale observed " + new Date(data.nodes.observer_observed_at).toLocaleTimeString() :
              "No fresh observer reading"}</p></div><Badge status={data.nodes?.status || "unavailable"}/></div>
            {nodes.length ? <div className="data-list">{nodes.map((node,i) => <div className="data-row" key={node.name+i}><div><span className="row-main">{node.name}</span><small>{node.models.length ? node.models.join(", ") : "No reported loaded models"}</small></div><span>{node.tailscale_online === true ? "● Online" : node.tailscale_online === false ? "○ Offline" : "Presence unverified"} · {node.inflight ?? "—"} tasks</span></div>)}</div> :
              <Empty title="No node reports yet" detail="Connect the authorized inventory endpoint; no devices are assumed online."/>}</section>
        </>}
        {tab === "traces" && <>
          <div className="page-intro"><p className="section-kicker">OBSERVABILITY</p><h1>Live activity<span className="accent">.</span></h1><p>Automatically refreshed about every 15 seconds. AssistX trace IDs and launcher job IDs are different types of evidence, not a proven shared lineage.</p></div>
          <section className="workspace-panel"><div className="panel-heading"><div><h2>Recent activity</h2><p>Metadata only · raw prompts and tool output are never forwarded.
            {data.traces?.status === "historical" ? " · Historical trace index; no recent execution observed." : ""}
            {data.traces?.last_event_at ? " · Latest event: " + new Date(data.traces.last_event_at).toLocaleString() : ""}
            </p></div>
            <Badge status={data.traces?.status === "live" && data.sessions?.status === "reported" ? "live" : "partial"}/></div>
            {timeline.length ? <div className="data-list">{timeline.map(item => <div className="data-row" key={item.key}>
              <div><span className="row-main trace-id">{item.kind} · {item.id}</span>
              <small>{item.time ? new Date(item.time).toLocaleString() : "No timestamp"}
                {item.model ? " · requested " + item.model : ""}
                {item.count != null ? " · " + item.count + " events" : ""}
                {item.hold ? " · archival hold" : ""}
                {!item.verified ? " · uncorrelated job receipt" : ""}
              </small></div><Badge status={item.status}/></div>)}</div> :
              <Empty title="No authenticated activity feed" detail="The private monitor-only fleet observer is unavailable. This page never synthesizes traces or uses AssistX execution credentials."/>}
          </section>
        </>}
        {Object.keys(errors).length > 0 && <p className="portal-warning" role="status">Some private telemetry endpoints are unavailable. The dashboard displays no unverified status for those feeds.</p>}
      </div>
    </main>
  </div>;
}
