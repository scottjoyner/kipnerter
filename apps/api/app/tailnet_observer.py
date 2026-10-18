"""Optional local-only, read-only Tailscale presence collector.

Publish through a separately authorized Tailscale Serve path (never Funnel).
Do not mount tailscaled's privileged socket inside the public API container.
"""
import hmac
import json
import os
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def sample():
    result = subprocess.run(
        ["tailscale", "status", "--json"], check=True, capture_output=True,
        text=True, timeout=5, env={"PATH": os.environ.get("PATH", "")},
    )
    status = json.loads(result.stdout)
    peers = list((status.get("Peer") or {}).values())
    self_node = status.get("Self")
    if isinstance(self_node, dict):
        peers.append(self_node)
    return {
        "source": "tailscale",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "nodes": [{
            "name": str(p.get("HostName") or "")[:80],
            "online": p.get("Online") is True,
            "os": str(p.get("OS") or "")[:24],
            "last_seen": str(p.get("LastSeen") or "")[:64],
        } for p in peers[:100] if p.get("HostName")],
    }


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, body):
        data = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._reply(200, {"status": "ok"})
        if self.path != "/v1/nodes":
            return self._reply(404, {"error": "not found"})
        secret = os.environ.get("FLEET_MONITOR_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        if len(secret) < 32 or not hmac.compare_digest(supplied, f"Bearer {secret}"):
            return self._reply(401, {"error": "unauthorized"})
        try:
            return self._reply(200, sample())
        except (OSError, subprocess.SubprocessError, ValueError):
            return self._reply(503, {"error": "collector unavailable"})

    def log_message(self, *_args):
        pass  # No credentials, query strings or identity in access logs.


if __name__ == "__main__":
    if len(os.environ.get("FLEET_MONITOR_TOKEN", "")) < 32:
        raise SystemExit("FLEET_MONITOR_TOKEN must be configured (>=32 chars)")
    host = os.environ.get("FLEET_MONITOR_BIND", "127.0.0.1")
    if host != "127.0.0.1":
        raise SystemExit("Non-loopback bind denied: publish through Tailscale Serve")
    port = int(os.environ.get("FLEET_MONITOR_PORT", "8769"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
