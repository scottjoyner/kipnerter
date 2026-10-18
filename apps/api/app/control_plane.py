"""Read-only, operator-authenticated projection; no arbitrary Tailnet proxying."""
import asyncio
import os
import re
from fastapi import APIRouter, Request, Response
import httpx
from .gateway import require_gateway_token, service_health
from .registry import services

router = APIRouter(prefix="/api/v1/control-plane", tags=["control-plane"])
AGENTS = ("assistx", "sophia", "hermes", "opencode", "fleet-monitor", "lmstudio")
TIMEOUT = httpx.Timeout(6.0, connect=3.0)


def _authorize(request: Request, response: Response) -> None:
    require_gateway_token(request)
    response.headers["Cache-Control"] = "private, no-store"


def _assistx_auth():
    user = os.getenv("ASSISTX_MONITOR_USER", "")
    password = os.getenv("ASSISTX_MONITOR_PASSWORD", "")
    if not user or not password:
        return None
    return httpx.BasicAuth(user, password)


async def _assistx_read(path: str, params: dict | None = None):
    service = next((s for s in services() if s.id == "assistx"), None)
    auth = _assistx_auth()
    if service is None or auth is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            result = await client.get(f"{service.base_url}{path}", params=params, auth=auth)
            result.raise_for_status()
            return result.json()
    except (httpx.HTTPError, ValueError):
        return None



async def _tailscale_read(path="/v1/nodes"):
    service = next((s for s in services() if s.id == "fleet-monitor"), None)
    token = os.getenv("FLEET_MONITOR_TOKEN", "")
    if not service or len(token) < 32:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            result = await client.get(
                f"{service.base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
            )
            result.raise_for_status()
            return result.json()
    except (httpx.HTTPError, ValueError):
        return None


@router.get("/overview")
async def overview(request: Request, response: Response):
    _authorize(request, response)
    configured = {s.id: s for s in services()}
    health = await asyncio.gather(*(service_health(s) for s in configured.values()))
    health_by_id = {h["id"]: h for h in health}
    return {
        "integrations": [
            {
                "id": name,
                "status": health_by_id[name]["status"] if name in health_by_id else "not_configured",
                "latency_ms": health_by_id[name]["latency_ms"] if name in health_by_id else None,
            }
            for name in AGENTS
        ],
        "source": "server-side health probes",
        "readonly": True,
    }


@router.get("/traces")
async def traces(request: Request, response: Response):
    _authorize(request, response)
    payload = await _assistx_read("/api/traces", {"limit": 25, "offset": 0})
    if not isinstance(payload, dict) or not isinstance(payload.get("traces"), list):
        return {"status": "unavailable", "traces": []}
    allowed_outcomes = {"open", "failed", "completed"}
    rows = []
    for item in payload["traces"][:25]:
        if not isinstance(item, dict):
            continue
        correlation = str(item.get("correlation_id") or "")[:128]
        if not correlation:
            continue
        rows.append({
            "correlation_id": correlation,
            "outcome": item.get("outcome") if item.get("outcome") in allowed_outcomes else "unknown",
            "events": item.get("events") if type(item.get("events")) is int else None,
            "last_ts_ms": item.get("last_ts_ms") if type(item.get("last_ts_ms")) is int else None,
            "duration_ms": item.get("duration_ms") if type(item.get("duration_ms")) is int else None,
        })
    return {"status": "live", "traces": rows}


@router.get("/nodes")
async def nodes(request: Request, response: Response):
    _authorize(request, response)
    assistx, tailnet = await asyncio.gather(
        _assistx_read("/api/fleet/nodes"), _tailscale_read()
    )
    raw_assistx = assistx.get("nodes", []) if isinstance(assistx, dict) else []
    tailnet_verified = isinstance(tailnet, dict) and isinstance(tailnet.get("nodes"), list)
    raw_tailnet = tailnet.get("nodes", []) if tailnet_verified else []
    if not isinstance(raw_assistx, list):
        raw_assistx = []
    if not isinstance(raw_tailnet, list):
        raw_tailnet = []
    by_name = {}
    for node in raw_assistx[:50]:
        if not isinstance(node, dict):
            continue
        name = str(node.get("hostname") or "")[:80]
        if not name or name.startswith("100."):
            continue
        by_name[name.lower()] = {
            "name": name, "source": "assistx",
            "models": [str(m)[:100] for m in (node.get("loaded_models") or [])[:12]],
            "last_seen": str(node.get("last_seen") or "")[:64],
            "inflight": node.get("inflight") if type(node.get("inflight")) is int else None,
            "tailscale_online": None,
        }
    for node in raw_tailnet[:100]:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "")[:80]
        if not name or name.startswith("100."):
            continue
        key = name.lower()
        row = by_name.setdefault(key, {
            "name": name, "source": "tailscale", "models": [],
            "last_seen": "", "inflight": None, "tailscale_online": None,
        })
        row["tailscale_online"] = node.get("online") if type(node.get("online")) is bool else None
    return {
        "status": "live" if tailnet_verified else
                  ("reported" if isinstance(assistx, dict) else "unavailable"),
        "tailscale_status": "live" if tailnet_verified else "unavailable",
        "assistx_status": "reported" if isinstance(assistx, dict) else "unavailable",
        "nodes": list(by_name.values())[:100],
    }

@router.get("/models")
async def model_inventory(request: Request, response: Response):
    _authorize(request, response)
    payload = await _assistx_read("/api/fleet/models")
    if not isinstance(payload, dict):
        return {"status": "unavailable", "models": []}
    raw = payload.get("models", {})
    if not isinstance(raw, dict):
        return {"status": "unavailable", "models": []}
    return {"status": "reported", "models": [
        {"id": str(name)[:120], "nodes": len((data or {}).get("nodes") or [])}
        for name, data in list(raw.items())[:50] if isinstance(data, dict)
    ]}



@router.get("/sessions")
async def agent_sessions(request: Request, response: Response):
    _authorize(request, response)
    payload = await _tailscale_read("/v1/sessions")
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        return {"status": "unavailable", "sessions": []}
    allowed_agents = {"hermes", "opencode"}
    allowed_states = {"QUEUED", "RUNNING", "COMPLETED", "COMPLETED_UNVERIFIED", "FAILED",
                      "TIMEOUT", "CANCELED", "START_FAILED"}
    results = []
    for item in payload["sessions"][:50]:
        if not isinstance(item, dict) or item.get("agent") not in allowed_agents:
            continue
        job_id = item.get("id")
        state = item.get("status")
        if not isinstance(job_id, str) or not re.fullmatch(r"job-[a-f0-9]{12}", job_id):
            continue
        if state not in allowed_states:
            continue
        results.append({
            "id": job_id,
            "agent": item["agent"],
            "status": state,
            "model": str(item.get("model") or "")[:120],
            "created_utc": str(item.get("created_utc") or "")[:45],
            "ended_utc": str(item.get("ended_utc") or "")[:45],
            "model_verified": item.get("model_verified") is True,
            "archive_verified": item.get("archive_verified") is True,
            "harvest_hold": item.get("harvest_hold") is True,
        })
    return {"status": "reported", "source": "fleet-agent-launcher",
            "sessions": results}
