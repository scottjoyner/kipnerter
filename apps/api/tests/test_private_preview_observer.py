import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from app.private_preview_observer import projection

NOW=datetime(2026,10,22,20,0,tzinfo=timezone.utc)
def record():
    return dict(api_image_verified=True,web_image_verified=True,deployed_sha_matches=True,
        funnel_disabled=True,private_route_correct=True,rollback_available=True,
        auth_qualified=False,production_release_authorized=False,production_modified=False,
        chat_http=200,release_http=200,auth_session_http=503,rollback_http=200,
        private_preview_status="ONLINE_AUTH_BLOCKED",scope="private_tailnet_preview",
        checked_utc=NOW.isoformat(),secret="do-not-return")
def write(tmp_path,d):
    p=tmp_path/"status.json";p.write_text(json.dumps(d));p.chmod(0o600);return p
def test_good(tmp_path):
    d=projection(write(tmp_path,record()),now=NOW)
    assert d["revision"]=="339210f30cbb8afde8d9ef212352ec055735058c"
    assert d["deployment"]=="ONLINE_AUTH_BLOCKED" and d["auth_qualified"] is False
    assert "do-not-return" not in json.dumps(d)
@pytest.mark.parametrize("name,value",[("rollback_available",False),("funnel_disabled",False),
    ("api_image_verified",False),("web_image_verified",False),("deployed_sha_matches",False),
    ("auth_qualified",True),("production_release_authorized",True),
    ("production_modified",True),("auth_session_http",200),("chat_http",503),
    ("private_preview_status","CHECK_REQUIRED"),("scope","production")])
def test_drift_denied(tmp_path,name,value):
    d=record();d[name]=value
    with pytest.raises(ValueError):projection(write(tmp_path,d),now=NOW)
@pytest.mark.parametrize("seconds",[-91,901])
def test_age_denied(tmp_path,seconds):
    d=record();d["checked_utc"]=(NOW-timedelta(seconds=seconds)).isoformat()
    with pytest.raises(ValueError):projection(write(tmp_path,d),now=NOW)
def test_missing_denied(tmp_path):
    with pytest.raises(FileNotFoundError):projection(tmp_path/"missing",now=NOW)
def test_bad_json_denied(tmp_path):
    p=tmp_path/"bad";p.write_text("{not json");p.chmod(0o600)
    with pytest.raises(ValueError):projection(p,now=NOW)
def test_group_perms_denied(tmp_path):
    p=write(tmp_path,record());p.chmod(0o640)
    with pytest.raises(ValueError):projection(p,now=NOW)
def test_symlink_denied(tmp_path):
    p=write(tmp_path,record());alias=tmp_path/"alias";alias.symlink_to(p)
    with pytest.raises(OSError):projection(alias,now=NOW)
def test_oversize_denied(tmp_path):
    p=tmp_path/"oversize";p.write_bytes(b"x"*8200);p.chmod(0o600)
    with pytest.raises(ValueError):projection(p,now=NOW)
def test_naive_time_denied(tmp_path):
    d=record();d["checked_utc"]="2026-10-22T20:00:00"
    with pytest.raises(ValueError):projection(write(tmp_path,d),now=NOW)

def test_live_http_endpoint_bearer_guard_and_allowlist(monkeypatch):
    """The newly added HTTP route must never bypass the existing bearer gate."""
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    from app import tailnet_observer

    fake_token = "unit-test-only-" + "x" * 40
    monkeypatch.setenv("FLEET_MONITOR_TOKEN", fake_token)
    monkeypatch.setattr(tailnet_observer, "private_preview_projection",
                        lambda: {"deployment": "ONLINE_AUTH_BLOCKED",
                                 "production_release_authorized": False})
    server = ThreadingHTTPServer(("127.0.0.1", 0), tailnet_observer.Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    endpoint = "http://127.0.0.1:" + str(server.server_port) + "/v1/private-preview"
    try:
        with pytest.raises(HTTPError) as denied:
            urlopen(endpoint, timeout=2)
        assert denied.value.code == 401
        with urlopen(Request(endpoint, headers={"Authorization": "Bearer " + fake_token}), timeout=2) as response:
            assert response.status == 200
            body = json.loads(response.read(4096))
            assert body == {"deployment": "ONLINE_AUTH_BLOCKED",
                            "production_release_authorized": False}
            assert response.headers["Cache-Control"] == "no-store"
        with pytest.raises(HTTPError) as invalid:
            urlopen(Request(endpoint, headers={"Authorization": "Bearer wrong"}), timeout=2)
        assert invalid.value.code == 401
    finally:
        server.shutdown()
        worker.join(timeout=3)
        server.server_close()
