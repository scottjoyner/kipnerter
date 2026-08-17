import hmac
import os
import time
from dataclasses import dataclass
from typing import Iterable

import httpx
from fastapi import HTTPException, Request, Response, status

from .registry import Service, services


MAX_BODY_BYTES = int(os.getenv("GATEWAY_MAX_BODY_BYTES", "1048576"))
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "20"))


@dataclass(frozen=True)
class AllowedRoute:
    service_id: str
    method: str
    path: str


# Deliberately exact-match only. Add routes here only after reviewing the
# upstream contract; this gateway must never become an arbitrary Tailnet proxy.
_ALLOWED_ROUTES: tuple[AllowedRoute, ...] = (
    AllowedRoute("assistx", "GET", "/health"),
    AllowedRoute("assistx", "POST", "/api/events"),
    AllowedRoute("assistx", "POST", "/api/sophia/events"),
    AllowedRoute("lmstudio", "GET", "/v1/models"),
    AllowedRoute("lmstudio", "POST", "/v1/chat/completions"),
)

_FORWARD_REQUEST_HEADERS = {"accept", "content-type", "user-agent"}
_FORWARD_RESPONSE_HEADERS = {"content-type", "cache-control"}


def _configured_token() -> str:
    return os.getenv("KIPNERTER_GATEWAY_TOKEN", "").strip()


def require_gateway_token(request: Request) -> None:
    configured = _configured_token()
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="gateway authentication is not configured",
        )

    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid gateway credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _service(service_id: str) -> Service:
    match = next((service for service in services() if service.id == service_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="service is not configured")
    return match


def _route_allowed(service_id: str, method: str, path: str) -> bool:
    return any(
        route.service_id == service_id and route.method == method.upper() and route.path == path
        for route in _ALLOWED_ROUTES
    )


def public_routes() -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for route in _ALLOWED_ROUTES:
        grouped.setdefault(route.service_id, []).append({"method": route.method, "path": route.path})
    return [{"service": service_id, "routes": routes} for service_id, routes in sorted(grouped.items())]


async def service_health(service: Service) -> dict:
    started = time.perf_counter()
    url = f"{service.base_url}{service.health_path}"
    try:
        async with httpx.AsyncClient(timeout=min(UPSTREAM_TIMEOUT_SECONDS, 5.0)) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {
            "id": service.id,
            "status": "healthy" if response.is_success else "degraded",
            "http_status": response.status_code,
            "latency_ms": latency_ms,
        }
    except httpx.HTTPError:
        return {
            "id": service.id,
            "status": "unavailable",
            "http_status": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }


async def proxy_request(service_id: str, upstream_path: str, request: Request) -> Response:
    require_gateway_token(request)
    service = _service(service_id)
    path = "/" + upstream_path.lstrip("/")
    if not _route_allowed(service_id, request.method, path):
        raise HTTPException(status_code=404, detail="gateway route is not available")

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body exceeds gateway limit")

    request_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in _FORWARD_REQUEST_HEADERS
    }

    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_SECONDS) as client:
            upstream = await client.request(
                request.method,
                f"{service.base_url}{path}",
                params=request.query_params,
                content=body,
                headers=request_headers,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="upstream service timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="upstream service is unavailable") from exc

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in _FORWARD_RESPONSE_HEADERS
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=None,
    )
