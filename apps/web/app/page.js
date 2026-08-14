const services = [
  ["Chat", "A shared conversation surface for web and Kipnerter iOS."],
  ["Sophia", "Voice and assistant experiences backed by the Kipnerter API."],
  ["AssistX", "Run agents, tools, and workflows from any authenticated device."],
  ["Research", "Launch research and ingestion jobs with traceable provenance."],
  ["MCP", "Discover and invoke approved MCP servers and tools."],
  ["Admin", "Operate models, services, queues, agents, and infrastructure."],
];

export default function Home() {
  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">KIPNERTER</p>
        <h1>Your AI systems, available anywhere.</h1>
        <p className="lead">
          The public web companion to Kipnerter iOS and the gateway to Sophia,
          AssistX, research, ingestion, MCP tooling, and private model infrastructure.
        </p>
        <div className="actions">
          <a href="/chat">Open chat</a>
          <a className="secondary" href="https://scottjoyner.dev">Admin</a>
        </div>
      </section>
      <section className="grid">
        {services.map(([name, description]) => (
          <article className="card" key={name}>
            <h2>{name}</h2>
            <p>{description}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
