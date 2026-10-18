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


def test_overview_distinguishes_observer_from_gateway(monkeypatch):
    from app import control_plane
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "valid-only")
    for key in ("ASSISTX_BASE_URL", "SOPHIA_BASE_URL", "LMSTUDIO_BASE_URL",
                "HERMES_BASE_URL", "OPENCODE_BASE_URL", "FLEET_MONITOR_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    async def observer(path="/v1/nodes"):
        assert path == "/v1/integrations"
        return {"integrations": [
            {"id": "assistx", "status": "healthy", "source": "local_loopback_probe", "latency_ms": 2},
            {"id": "sophia", "status": "healthy", "source": "local_loopback_probe", "latency_ms": 1},
            {"id": "opencode", "status": "unverified", "source": "session_ledger_only"},
        ]}
    monkeypatch.setattr(control_plane, "_tailscale_read", observer)
    res = client.get("/api/v1/control-plane/overview", headers={
        "Authorization": "Bearer valid-only"
    })
    assert res.status_code == 200
    by_id = {entry["id"]: entry for entry in res.json()["integrations"]}
    assert by_id["sophia"]["status"] == "healthy"
    assert by_id["sophia"]["gateway_status"] == "not_configured"
    assert by_id["sophia"]["source"] == "x1_observer"
    assert by_id["opencode"]["status"] == "unverified"
    assert res.headers["cache-control"] == "private, no-store"


def test_observer_rejects_replayed_future_or_wrong_source_payloads():
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)
    data = {"source": "tailscale", "observed_at": now.isoformat(), "nodes": []}
    assert control_plane._observer_is_fresh(data, "/v1/nodes", now)
    assert not control_plane._observer_is_fresh(data, "/v1/sessions", now)
    assert not control_plane._observer_is_fresh(data | {
        "observed_at": (now-timedelta(minutes=3)).isoformat(),
    }, "/v1/nodes", now)
    assert not control_plane._observer_is_fresh(data | {
        "observed_at": (now+timedelta(minutes=1)).isoformat(),
    }, "/v1/nodes", now)
    assert not control_plane._observer_is_fresh(data | {
        "observed_at": "2026-10-18T16:00:00",
    }, "/v1/nodes", now)
    assert not control_plane._observer_is_fresh(data | {
        "source": "spoofed", "observed_at": "irrelevant",
    }, "/v1/nodes", now)
    assert not control_plane._observer_is_fresh(None, "/v1/nodes", now)
