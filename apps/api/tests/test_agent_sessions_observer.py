import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app import agent_sessions_observer as observer
from app import control_plane
from app.main import app


def _write(path, overrides=None):
    record = {
        "id": path.stem, "agent": "hermes", "status": "COMPLETED",
        "model": "gpt-5.6-luna", "created_utc": "2026-10-17T20:00:00Z",
        "model_witness": "NOT_VERIFIED", "offload_verified": False,
        "harvest_status": "BLOCKED_SECURITY_HOLD_knowledge_173",
        "prompt_path": "/secret/source/dir", "prompt": "DO_NOT_EXPORT",
        "session_id": "PRIVATE-NATIVE-SESSION", "user": "private-account",
    }
    record.update(overrides or {})
    path.write_text(json.dumps(record))
    return record


def test_local_projection_never_exports_raw_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEET_AGENT_STATE_DIR", str(tmp_path))
    _write(tmp_path / "job-aaaaaaaaaaaa.json")
    data = observer.sessions()
    assert data["total"] == 1
    row = data["sessions"][0]
    assert row["id"] == "job-aaaaaaaaaaaa"
    assert row["harvest_hold"] is True
    assert row["archive_verified"] is False
    assert row["model_verified"] is False
    for value in ("DO_NOT_EXPORT", "PRIVATE-NATIVE-SESSION", "/secret/", "private-account"):
        assert value not in json.dumps(data)


def test_ledger_rejects_symlinks_and_mismatched_ids(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEET_AGENT_STATE_DIR", str(tmp_path))
    original = tmp_path / "data.json"
    _write(original)
    link = tmp_path / "job-aaaaaaaaaaaa.json"
    link.symlink_to(original)
    with pytest.raises(ValueError):
        observer.sessions()
    link.unlink()
    _write(link, {"id": "job-bbbbbbbbbbbb"})
    with pytest.raises(ValueError):
        observer.sessions()


def test_missing_ledger_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEET_AGENT_STATE_DIR", str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        observer.sessions()


def test_control_plane_sessions_requires_token(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "private-gateway-token")
    result = TestClient(app).get("/api/v1/control-plane/sessions")
    assert result.status_code == 401


def test_sessions_projected_again_without_raw_leaks(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "private-gateway-token")
    async def fake_read(path="/v1/nodes"):
        assert path == "/v1/sessions"
        return {"sessions": [{"id": "job-aaaaaaaaaaaa", "agent": "opencode",
                               "status": "RUNNING", "model": "safe-model",
                               "harvest_hold": True, "private": "UNSAFE"}]}
    monkeypatch.setattr(control_plane, "_tailscale_read", fake_read)
    r = TestClient(app).get("/api/v1/control-plane/sessions", headers={
        "Authorization": "Bearer private-gateway-token"
    })
    assert r.status_code == 200
    assert r.json()["sessions"][0]["status"] == "RUNNING"
    assert "UNSAFE" not in r.text
    assert r.headers["cache-control"] == "private, no-store"
