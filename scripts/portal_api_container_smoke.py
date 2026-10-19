"""Run exact API 0.3.1 plus authenticated portal contract inside no-network container."""
import os
import json
from fastapi.testclient import TestClient
from app.main import app

TOKEN = os.environ["KIPNERTER_GATEWAY_BEARER_TOKEN"]
RELEASE_SHA = os.environ["KIPNERTER_RELEASE_SHA"]
CONTROL_PLANE = ("overview", "nodes", "models", "traces", "sessions")
unauthenticated = [
    ("/health", 200),
    ("/ready", 200),
    ("/version", 200),
    ("/api/v1", 200),
    ("/api/v1/models", 200),
    ("/api/v1/release", 200),
    ("/metrics", 401),
    ("/api/v1/gateway/lmstudio/v1/models", 401),
]
verified = 0
with TestClient(app) as client:
    for route, expected in unauthenticated:
        response = client.get(route)
        assert response.status_code == expected, (route, response.status_code, expected)
        if route == "/api/v1/release":
            assert response.json() == {"source": "kipnerter-api", "revision": RELEASE_SHA}
            assert response.headers.get("cache-control") == "no-store"
        verified += 1
    for route in CONTROL_PLANE:
        url = "/api/v1/control-plane/" + route
        denied = client.get(url)
        assert denied.status_code == 401, (url, denied.status_code)
        permitted = client.get(url, headers={"Authorization": "Bearer " + TOKEN})
        assert permitted.status_code == 200, (url, permitted.status_code)
        assert permitted.headers.get("cache-control") == "private, no-store"
        assert isinstance(permitted.json(), dict)
        verified += 2
    forbidden = client.post("/api/v1/control-plane/chat",
        headers={"Authorization": "Bearer " + TOKEN},
        json={"prompt": "must never execute"})
    assert forbidden.status_code == 404
    verified += 1
print(f"source-pinned 0.3.1 portal compatibility smoke {verified}/{verified}, network=none, filesystem=read-only, deployed=false")
