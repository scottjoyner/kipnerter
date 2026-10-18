"""Optional local-only, read-only Tailscale presence collector.

Publish through a separately authorized Tailscale Serve path (never Funnel).
Do not mount tailscaled's privileged socket inside the public API container.
"""
import hmac
import json
import os
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .agent_sessions_observer import sessions
from .trace_snapshot_observer import recent_traces
from .assistx_fleet_observer import inventory


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


# Purely read-only probes with hardcoded local destinations. Avoid responding
# with URLs, auth headers, process commandlines or upstream response bodies.
_INTEGRATION_HEALTH = {
    "assistx": "http://127.0.0.1:8000/health",
    "sophia": "http://127.0.0.1:8790/healthz",
}
_SERVICE_UNITS = {"hermes": "hermes-gateway.service"}


def integration_status():
    integrations = []
    for name, url in _INTEGRATION_HEALTH.items():
        started = time.monotonic()
        try:
            request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=2) as reply:
                healthy = reply.status == 200
        except (OSError, ValueError, urllib.error.HTTPError):
            healthy = False
        integrations.append({
            "id": name,
            "status": "healthy" if healthy else "unavailable",
            "source": "local_loopback_probe",
            "latency_ms": round((time.monotonic()-started)*1000),
        })
    for name, unit in _SERVICE_UNITS.items():
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                capture_output=True, text=True, timeout=2, check=False,
            )
            healthy = result.returncode == 0 and result.stdout.strip() == "active"
        except (OSError, subprocess.SubprocessError):
            healthy = False
        integrations.append({
            "id": name, "status": "healthy" if healthy else "unavailable",
            "source": "local_systemd_presence", "latency_ms": None,
        })
    # OpenCode is a CLI, not an always-running service. A launcher job ledger
    # or a catalog row is not evidence that an OpenCode worker is live now.
    integrations.append({
        "id": "opencode", "status": "unverified",
        "source": "session_ledger_only", "latency_ms": None,
    })
    return {
        "source": "x1-370",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "integrations": integrations,
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
        if self.path not in ("/v1/nodes", "/v1/sessions", "/v1/integrations", "/v1/traces", "/v1/assistx-fleet"):
            return self._reply(404, {"error": "not found"})
        secret = os.environ.get("FLEET_MONITOR_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        if len(secret) < 32 or not hmac.compare_digest(supplied, f"Bearer {secret}"):
            return self._reply(401, {"error": "unauthorized"})
        try:
            data = {
                "/v1/nodes": sample,
                "/v1/sessions": sessions,
                "/v1/integrations": integration_status,
                "/v1/traces": recent_traces,
                "/v1/assistx-fleet": inventory,
            }
            return self._reply(200, data[self.path]())
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, UnicodeError):
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
