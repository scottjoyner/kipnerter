from fastapi.testclient import TestClient
from app.main import app
from app import control_plane

client = TestClient(app)


def test_control_plane_denies_no_token(monkeypatch):
    monkeypatch.delenv("KIPNERTER_GATEWAY_TOKEN", raising=False)
    for path in ("overview", "models", "nodes", "traces"):
        assert client.get(f"/api/v1/control-plane/{path}").status_code == 503


def test_control_plane_rejects_invalid_token(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "valid-only")
    assert client.get("/api/v1/control-plane/traces", headers={
        "Authorization": "Bearer invalid"
    }).status_code == 401


def test_control_plane_overview_is_redacted(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "valid-only")
    for name in ("ASSISTX_BASE_URL", "SOPHIA_BASE_URL", "LMSTUDIO_BASE_URL",
                 "HERMES_BASE_URL", "OPENCODE_BASE_URL", "FLEET_MONITOR_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    response = client.get("/api/v1/control-plane/overview", headers={
        "Authorization": "Bearer valid-only"
    })
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    status = {r["id"]: r["status"] for r in response.json()["integrations"]}
    assert set(status) == {"assistx", "sophia", "hermes", "opencode", "fleet-monitor", "lmstudio"}
    assert set(status.values()) == {"not_configured"}
    assert "base_url" not in response.text


def test_traces_only_return_allowlisted_metadata(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "valid-only")
    async def fake_read(path, params=None):
        assert path == "/api/traces"
        return {"traces": [{"correlation_id": "abc", "outcome": "failed",
                            "events": 8, "duration_ms": 120,
                            "payload": {"password": "DO-NOT-LEAK"},
                            "prompt": "SENSITIVE", "last_ts_ms": 1234}]}
    monkeypatch.setattr(control_plane, "_assistx_read", fake_read)
    response = client.get("/api/v1/control-plane/traces", headers={"Authorization": "Bearer valid-only"})
    assert response.status_code == 200
    assert response.json()["traces"][0]["correlation_id"] == "abc"
    assert "DO-NOT-LEAK" not in response.text and "SENSITIVE" not in response.text


def test_nodes_do_not_expose_tailnet_ip(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "valid-only")
    async def fake_read(path, params=None):
        return {"nodes": [{"hostname": "xwing", "ip": "100.11.22.33",
                           "loaded_models": ["model-a"], "inflight": 2}]}
    monkeypatch.setattr(control_plane, "_assistx_read", fake_read)
    response = client.get("/api/v1/control-plane/nodes", headers={"Authorization": "Bearer valid-only"})
    assert response.status_code == 200
    assert "100.11.22.33" not in response.text
    assert response.json()["nodes"][0]["name"] == "xwing"


def test_no_unauthenticated_exec_surface(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "valid-only")
    response = client.post("/api/v1/control-plane/traces", headers={
        "Authorization": "Bearer valid-only"
    })
    assert response.status_code == 405
