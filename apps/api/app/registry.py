import os
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class Service:
    id: str
    kind: str
    base_url: str
    network: str = "tailscale"
    health_path: str = "/health"

    def public_dict(self) -> dict:
        data = asdict(self)
        # The API exposes topology metadata but never credentials.
        return data


def _service(service_id: str, kind: str, env_name: str, health_path: str = "/health") -> Optional[Service]:
    value = os.getenv(env_name, "").strip().rstrip("/")
    if not value:
        return None
    return Service(service_id, kind, value, "tailscale", health_path)


def services() -> list[Service]:
    candidates = [
        _service("assistx", "agent-gateway", "ASSISTX_BASE_URL"),
        _service("sophia", "voice", "SOPHIA_BASE_URL"),
        _service("lmstudio", "openai-compatible", "LMSTUDIO_BASE_URL", "/v1/models"),
    ]
    return [service for service in candidates if service is not None]


def models() -> list[dict]:
    # Provider/model discovery will replace this bootstrap view once remote
    # OpenAI-compatible endpoints are connected.
    return [
        {
            "provider": service.id,
            "discovery_url": f"{service.base_url}/v1/models",
        }
        for service in services()
        if service.kind == "openai-compatible"
    ]
