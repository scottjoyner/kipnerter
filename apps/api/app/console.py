"""Read-only, bounded adapters for the authenticated web control plane."""
import asyncio
import os
import re
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request

from .gateway import require_gateway_token
from .registry import services

router = APIRouter(prefix="/api/v1/console", tags=["console"])
_EXTRA = (
    ("hermes", "HERMES_BASE_URL", "/health"),
    ("opencode", "OPENCODE_BASE_URL", "/health"),
    ("tailscale", "FLEET_MONITOR_BASE_URL", "/health"),
    ("traces", "TRACES_BASE_URL", "/health"),
)
_ID = re.compile(r"^[a-zA-Z0-9_-]{8,96}$")
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._ -]")
_TIMEOUT = httpx.Timeout(3.0)


def _base(value: str) -> str:
    base = os.getenv(value, "").strip().rstrip("/")
    if not base:
        return ""
    if not (base.startswith("http://") or base.startswith("https://")):
        return ""
    return base


def _auth(request: Request) -> None:
    require_gateway_token(request)


async def _probe(service_id: str, base: str, path: str) -> dict:
    started = time.perf_counter()
    if not base:
        return {"id": service_id, "state": "unconfigured", "configured": False}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            result = await client.get(base + path)
        state = "responding" if result.status_code < 500 else "degraded"
        if result.status_code in (401, 403):
            state = "authentication_required"
        return {"id": service_id, "state": state, "configured": True,
                "latency_ms": round((time.perf_counter() - started) * 1000)}
    except httpx.HTTPError:
        return {"id": service_id, "state": "unreachable", "configured": True}


@router.get("/status")
async def console_status(request: Request) -> dict:
    _auth(request)
    live = [(s.id, s.base_url, s.health_path) for s in services()]
    live_ids = {s[0] for s in live}
    live += [(name, _base(env), path) for name, env, path in _EXTRA if name not in live_ids]
    found = await asyncio.gather(*(_probe(*s) for s in live))
    return {"observed_at": datetime.now(timezone.utc).isoformat(),
            "services": found, "note": "Health checks do not establish model admission or execution readiness"}


@router.get("/nodes")
async def console_nodes(request: Request) -> dict:
    _auth(request)
    base = _base("FLEET_MONITOR_BASE_URL")
    token = os.getenv("FLEET_MONITOR_READ_TOKEN", "").strip()
    if not base or not token:
        return {"configured": False, "nodes": [], "reason": "collector_not_configured"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            response = await client.get(base + "/api/v1/nodes",
                                        headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        data = response.json()
        nodes = data.get("nodes", []) if isinstance(data, dict) else []
        if not isinstance(nodes, list):
            raise ValueError("invalid nodes")
        safe = []
        for n in nodes[:128]:
            if not isinstance(n, dict):
                continue
            name = _SAFE_NAME.sub("", str(n.get("name", "")))[:72]
            if name:
                safe.append({"name": name, "online": n.get("online") is True})
        return {"configured": True, "nodes": safe, "observed_at": datetime.now(timezone.utc).isoformat()}
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(status_code=502, detail="fleet monitor unavailable")


@router.get("/traces/{trace_id}")
async def console_trace(trace_id: str, request: Request) -> dict:
    _auth(request)
    if not _ID.fullmatch(trace_id):
        raise HTTPException(status_code=400, detail="invalid trace id")
    base = _base("TRACES_BASE_URL") or _base("ASSISTX_BASE_URL")
    token = os.getenv("TRACES_READ_TOKEN", "").strip()
    if not base or not token:
        raise HTTPException(status_code=503, detail="trace reader not configured")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            response = await client.get(base + "/api/traces/" + trace_id,
                                        headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="trace not found")
        response.raise_for_status()
        raw = response.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="trace reader unavailable")
    except ValueError:
        raise HTTPException(status_code=502, detail="invalid trace reader response")
    # Never relay prompts, tool arguments, payloads, credentials, or raw logs.
    events = raw.get("events", []) if isinstance(raw, dict) else []
    if not isinstance(events, list):
        events = []
    safe = []
    for e in events[:100]:
        if isinstance(e, dict):
            safe.append({key: str(e[key])[:120] for key in
                         ("type", "status", "timestamp", "service", "actor_type")
                         if key in e and isinstance(e[key], (str, int, float, bool))})
    return {"trace_id": trace_id, "events": safe, "truncated": len(events) > 100,
            "detail": "Allowlisted trace metadata only. Payloads are never returned."}
