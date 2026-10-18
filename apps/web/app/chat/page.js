import { getServerSession } from "next-auth";
import { authOptions, authReady, isAllowed } from "../../lib/auth";
import FleetConsole from "./console";
export const dynamic = "force-dynamic";
export const metadata = { title: "Chat & Fleet | Kipnerter" };
export default async function ChatPage() {
  const session = authReady ? await getServerSession(authOptions) : null;
  if (isAllowed(session?.user?.email, session?.user?.id)) {
    return <FleetConsole email={session.user.email} />;
  }
  return <main className="auth-shell">
    <a href="/" className="wordmark">KIPNERTER <span> / FLEET</span></a>
    <section className="auth-card">
      <div className="auth-glyph">K</div>
      <p className="eyebrow">PRIVATE AI WORKSPACE</p>
      <h1>One place for your AI fleet.</h1>
      <p>Chat, agents, inference, node monitoring, and correlated traces. The portal is public; your fleet stays private.</p>
      {authReady ? <a className="primary-btn" href="/api/auth/signin/tailscale?callbackUrl=%2Fchat">Sign in with Tailscale identity →</a> :
        <div className="auth-warning">Fleet login is not yet configured. An administrator must configure the Tailscale OIDC identity provider and access policy.</div>}
      <p className="fine-print">Authorization is checked before any fleet telemetry is retrieved. This site never exposes Tailnet credentials.</p>
    </section>
  </main>;
}
