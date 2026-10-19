"""No-network ASGI smoke for exact build image; all credentials are synthetic."""
from fastapi.testclient import TestClient
from app.main import app

CHECKS = [
    ("/health", 200),
    ("/ready", 200),
    ("/version", 200),
    ("/api/v1", 200),
    ("/api/v1/models", 200),
    ("/metrics", 401),
    ("/api/v1/gateway/lmstudio/v1/models", 401),
]

with TestClient(app) as client:
    for path, expected in CHECKS:
        result = client.get(path)
        assert result.status_code == expected, (path, result.status_code, expected)

print("source-pinned isolated ASGI image preflight 7/7; no deployment or model execution")
