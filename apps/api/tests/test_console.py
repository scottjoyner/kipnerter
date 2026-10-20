import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def default_deny(monkeypatch):
    for key in ("KIPNERTER_GATEWAY_TOKEN", "ASSISTX_BASE_URL", "SOPHIA_BASE_URL",
                "LMSTUDIO_BASE_URL", "HERMES_BASE_URL", "OPENCODE_BASE_URL",
                "FLEET_MONITOR_BASE_URL", "FLEET_MONITOR_READ_TOKEN",
                "TRACES_BASE_URL", "TRACES_READ_TOKEN"):
        monkeypatch.delenv(key, raising=False)


def test_console_denies_without_gateway_auth():
    for route in ("/api/v1/console/status", "/api/v1/console/nodes",
                  "/api/v1/console/traces/abcdefgh"):
        response = client.get(route)
        assert response.status_code == 503


def test_console_denies_incorrect_gateway_token(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "correct")
    response = client.get("/api/v1/console/status", headers={"Authorization": "Bearer incorrect"})
    assert response.status_code == 401


def test_unconfigured_services_no_private_data(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "correct")
    response = client.get("/api/v1/console/status", headers={"Authorization": "Bearer correct"})
    assert response.status_code == 200
    services = response.json()["services"]
    assert {s["id"] for s in services} >= {"hermes", "opencode", "tailscale", "traces"}
    assert all(s["state"] == "unconfigured" for s in services)
    assert "base_url" not in response.text


def test_nodes_fail_closed_without_collector(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "correct")
    response = client.get("/api/v1/console/nodes", headers={"Authorization": "Bearer correct"})
    assert response.json() == {"configured": False, "nodes": [], "reason": "collector_not_configured"}


def test_traces_fail_closed_and_validate_identifier(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "correct")
    headers = {"Authorization": "Bearer correct"}
    assert client.get("/api/v1/console/traces/a", headers=headers).status_code == 400
    assert client.get("/api/v1/console/traces/abcdefgh", headers=headers).status_code == 503
