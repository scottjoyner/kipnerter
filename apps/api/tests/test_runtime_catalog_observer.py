from datetime import datetime, timezone
from app.runtime_catalog_observer import read_catalog
from app import control_plane
from app.main import app
from fastapi.testclient import TestClient
import pytest

def sample():
    return {"models":[
        {"key":"publisher/my-private-model-path.gguf",
         "display_name":"Model A 3B Q4", "type":"llm", "loaded_instances":[]},
        {"key":"a-user/hidden-file.gguf",
         "display_name":"/Users/secret/weights.bin",
         "type":"embedding", "loaded_instances":[{"id":"private-instance-secret"}]},
    ]}

def test_read_catalog_redacts_paths_and_instances():
    result=read_catalog(fetch=sample,now=datetime(2026,10,18,20,0,tzinfo=timezone.utc))
    assert result["source"]=="lmstudio_native_catalog"
    assert len(result["models"])==2
    assert result["models"][0]["name"]=="Model A 3B Q4"
    assert result["models"][0]["loaded_instances"]==0
    assert result["models"][0]["runtime_reported_loaded"] is False
    assert result["models"][1]["loaded_instances"]==1
    assert result["models"][1]["independently_verified"] is False
    assert "secret" not in str(result).lower()
    assert "private" not in str(result).lower()
    assert "publisher/" not in str(result)

def test_native_catalog_fail_closed_and_bounded():
    for payload in ({}, {"models":{}}, {"models":[{}]*1001},
                    {"models":[{"key":"a","loaded_instances":[{}]*65}]}):
        if len(payload.get("models",[]))>1000 or "models" not in payload or not isinstance(payload["models"],list):
            with pytest.raises(ValueError):read_catalog(fetch=lambda:payload)
        else:
            assert read_catalog(fetch=lambda:payload)["models"]==[]

def test_api_labels_assistx_empty_vs_runtime_catalog(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN","only-synthetic")
    stamp=datetime.now(timezone.utc).isoformat()
    async def remote(path="/v1/nodes"):
        if path=="/v1/assistx-fleet":
            return {"source":"assistx_local_inventory", "observed_at":stamp,
                    "models":[],"nodes":[]}
        assert path=="/v1/runtime-catalog"
        return {"source":"lmstudio_native_catalog","observed_at":stamp,
                "models":[{"id":"lmstudio-0123456789abcdef0123","name":"Model A 3B Q4",
                           "kind":"llm","loaded_instances":0,"runtime_reported_loaded":False,
                           "independently_verified":False}]}
    monkeypatch.setattr(control_plane,"_tailscale_read",remote)
    res=TestClient(app).get("/api/v1/control-plane/models",
                            headers={"Authorization":"Bearer only-synthetic"})
    assert res.status_code==200
    data=res.json()
    assert data["status"]=="reported"
    assert data["assistx_status"]=="reported_empty"
    assert data["runtime_status"]=="reported"
    assert data["models"][0]["status"]=="catalog_available"
    assert data["models"][0]["loaded_instances"]==0
    assert data["models"][0]["independently_verified"] is False

def test_runtime_observation_source_requires_timestamp():
    from datetime import timedelta
    now=datetime.now(timezone.utc)
    good={"source":"lmstudio_native_catalog","observed_at":now.isoformat()}
    assert control_plane._observer_is_fresh(good,"/v1/runtime-catalog",now)
    bad=good | {"observed_at":(now-timedelta(minutes=5)).isoformat()}
    assert not control_plane._observer_is_fresh(bad,"/v1/runtime-catalog",now)

def test_api_filters_invalid_runtime_metadata(monkeypatch):
    monkeypatch.setenv("KIPNERTER_GATEWAY_TOKEN", "only-synthetic")
    stamp=datetime.now(timezone.utc).isoformat()
    async def remote(path="/v1/nodes"):
        if path=="/v1/assistx-fleet":
            return {"source":"assistx_local_inventory","observed_at":stamp,"models":[],"nodes":[]}
        assert path=="/v1/runtime-catalog"
        return {"source":"lmstudio_native_catalog","observed_at":stamp,"models":[
            {"id":"lmstudio-0123456789abcdef0123","name":"/private/model", "loaded_instances":0},
            {"id":"lmstudio-0123456789abcdef0123","name":"Model A","loaded_instances":-1},
            {"id":"lmstudio-0123456789abcdef0123","name":"Model B","loaded_instances":1},
        ]}
    monkeypatch.setattr(control_plane,"_tailscale_read",remote)
    data=TestClient(app).get("/api/v1/control-plane/models",headers={
        "Authorization":"Bearer only-synthetic"}).json()
    assert len(data["models"])==1
    assert data["models"][0]["status"]=="runtime_reported_loaded"
    assert data["models"][0]["independently_verified"] is False
    assert "/private/model" not in str(data)
