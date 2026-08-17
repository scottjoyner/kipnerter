import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Service:
    id: str
    kind: str
    base_url: str
    network: str = "tailscale"
    health_path: str = "/health"

    def public_dict(self) -> dict:
        # Public clients only need stable capability metadata. The private
        # Tailnet address stays server-side for gateway/proxy use.
        return {
            "id": self.id,
            "kind": self.kind,
            "configured": True,
            "availability": "private",
            "health_path": self.health_path,
        }


def _service(service_id: str, kind: str, env_name: str, health_path: str = "/health") -> Optional[Service]:
    value = os.getenv(env_name, "").strip().rstrip("/")
    if not value:
        return None
    return Service(service_id, kind, value, "tailscale", health_path)


def services() -> list[Service]:
    candidates = [
        _service("assistx", "agent-gateway", "ASSISTX_BASE_URL"),
        _service("sophia", "voice", "SOPHIA_BASE_URL", "/"),
        _service("lmstudio", "openai-compatible", "LMSTUDIO_BASE_URL", "/v1/models"),
    ]
    return [service for service in candidates if service is not None]


def models() -> list[dict]:
    # Keep private provider URLs internal. Gateway routes proxy provider
    # discovery without exposing Tailnet topology to public clients.
    return [
        {
            "provider": service.id,
            "configured": True,
            "availability": "private",
        }
        for service in services()
        if service.kind == "openai-compatible"
    ]
