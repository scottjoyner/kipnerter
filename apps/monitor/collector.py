"""Minimal read-only Tailscale node collector.

Deploy ONLY behind Tailscale Serve (private), never through public Funnel.
No shell input, no addresses, no ACLs, no arbitrary commands are exposed.
"""
import hmac
import json
import os
import re
import subprocess
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="Kipnerter private node collector", docs_url=None, redoc_url=None)
_SAFE = re.compile(r"[^a-zA-Z0-9._ -]")


def authorize(authorization: str | None) -> None:
    expected = os.getenv("FLEET_MONITOR_READ_TOKEN", "").strip()
    scheme, _, actual = (authorization or "").partition(" ")
    if not expected:
        raise HTTPException(status_code=503, detail="collector authentication not configured")
    if scheme.lower() != "bearer" or not hmac.compare_digest(expected, actual):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/nodes")
def nodes(authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        result = subprocess.run(["tailscale", "status", "--json"], check=True,
                                capture_output=True, timeout=5, text=True)
        payload = json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        raise HTTPException(status_code=503, detail="tailscale status unavailable")
    peers = list((payload.get("Peer") or {}).values())
    if isinstance(payload.get("Self"), dict):
        peers.append(payload["Self"])
    safe = []
    for peer in peers[:128]:
        if not isinstance(peer, dict):
            continue
        name = _SAFE.sub("", str(peer.get("HostName") or ""))[:72]
        if name:
            safe.append({"name": name, "online": peer.get("Online") is True})
    return {"observed_at": datetime.now(timezone.utc).isoformat(),
            "nodes": sorted(safe, key=lambda node: node["name"])}
