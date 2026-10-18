import { currentSession, allowedUser, identityReady } from "../../lib/auth";
import FleetConsole from "./FleetConsole";
import { SignInButton } from "./SignInButton";
import "./console.css";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Fleet Console | Kipnerter",
  description: "Authenticated model, agent, node, and trace control plane."
};

export default async function ChatPage() {
  const session = identityReady ? await currentSession() : null;
  if (!allowedUser(session)) {
    return (
      <main className="console-entry">
        <div className="entry-mark">K / KIPNERTER</div>
        <div className="entry-panel">
          <span className="entry-overline">PRIVATE FLEET · SECURE ACCESS</span>
          <h1>One home for your AI fleet.</h1>
          <p>Chat with approved models, see your services and nodes, and inspect bounded execution traces.</p>
          <div className="entry-features"><span>AssistX</span><span>Sophia</span><span>Hermes</span><span>OpenCode</span><span>Tailscale</span></div>
          {identityReady ? <SignInButton /> : <p className="entry-warning">Identity sign-in is not configured. Fleet access is disabled.</p>}
          <p className="entry-foot">Only approved identities can view fleet data. No direct public access to private nodes.</p>
        </div>
        <a className="entry-back" href="/">← Back to Kipnerter</a>
      </main>
    );
  }
  return <FleetConsole user={session.user.email} chatEnabled={process.env.KIPNERTER_WEB_CHAT_ENABLED === "true"} />;
}
