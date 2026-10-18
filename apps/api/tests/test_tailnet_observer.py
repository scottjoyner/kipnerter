import json
from app import tailnet_observer


def test_collector_drops_private_ips_and_credentials(monkeypatch):
    class Result:
        stdout = json.dumps({"Self": {"HostName": "x1-370", "Online": True, "TailscaleIPs": ["100.64.1.1"]},
                            "Peer": {"peer": {"HostName": "xwing", "Online": False,
                                              "OS": "linux", "TailscaleIPs": ["100.10.20.30"],
                                              "LastSeen": "2026-10-15"}}})
    monkeypatch.setattr(tailnet_observer.subprocess, "run", lambda *_a, **_kw: Result())
    result = tailnet_observer.sample()
    assert result["source"] == "tailscale"
    assert {n["name"] for n in result["nodes"]} == {"xwing", "x1-370"}
    assert "100.10.20.30" not in json.dumps(result)
    assert any(n["online"] is False for n in result["nodes"])


def test_integrations_report_real_checks_but_no_private_addresses(monkeypatch):
    from app import tailnet_observer as observer
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
    class Unit:
        returncode = 0
        stdout = "active\n"
    monkeypatch.setattr(observer.urllib.request, "urlopen", lambda *_a, **_kw: Reply())
    monkeypatch.setattr(observer.subprocess, "run", lambda *_a, **_kw: Unit())
    result = observer.integration_status()
    statuses = {item["id"]: item for item in result["integrations"]}
    assert statuses["assistx"]["status"] == "healthy"
    assert statuses["sophia"]["status"] == "healthy"
    assert statuses["hermes"]["status"] == "healthy"
    assert statuses["opencode"]["status"] == "unverified"
    assert "127.0.0.1" not in json.dumps(result)
