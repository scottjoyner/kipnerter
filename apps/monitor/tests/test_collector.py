import json
import subprocess
from fastapi.testclient import TestClient
from collector import app

client = TestClient(app)


def test_collector_unconfigured_denies(monkeypatch):
    monkeypatch.delenv("FLEET_MONITOR_READ_TOKEN", raising=False)
    assert client.get("/api/v1/nodes").status_code == 503


def test_collector_requires_correct_token(monkeypatch):
    monkeypatch.setenv("FLEET_MONITOR_READ_TOKEN", "secret")
    assert client.get("/api/v1/nodes", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_collector_sanitizes_output(monkeypatch):
    monkeypatch.setenv("FLEET_MONITOR_READ_TOKEN", "secret")
    example = {"Self": {"HostName": "control", "Online": True, "TailscaleIPs": ["100.1.2.3"]},
               "Peer": {"1": {"HostName": "agent<script>", "Online": True, "TailscaleIPs": ["100.5.6.7"]}}}
    def fixed_command(args, **kwargs):
        assert args == ["tailscale", "status", "--json"]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(example), stderr="")
    monkeypatch.setattr(subprocess, "run", fixed_command)
    r = client.get("/api/v1/nodes", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    assert r.json()["nodes"] == [{"name": "agentscript", "online": True}, {"name": "control", "online": True}]
    assert "100." not in r.text


def test_collector_does_not_mask_cli_failure(monkeypatch):
    monkeypatch.setenv("FLEET_MONITOR_READ_TOKEN", "secret")
    def failed(*args, **kwargs):
        raise subprocess.TimeoutExpired("tailscale", timeout=5)
    monkeypatch.setattr(subprocess, "run", failed)
    assert client.get("/api/v1/nodes", headers={"Authorization": "Bearer secret"}).status_code == 503
