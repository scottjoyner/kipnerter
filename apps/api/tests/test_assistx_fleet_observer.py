import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import pytest

from app.assistx_fleet_observer import inventory

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from scripts.refresh_assistx_fleet_snapshot import refresh

def fixture(now=None,nodes=None,models=None):
    return {"source":"assistx_local_inventory",
            "observed_at":(now or datetime.now(timezone.utc)).isoformat(),
            "nodes":nodes if nodes is not None else [],
            "models":models if models is not None else []}

def private_file(tmp_path,data):
    file=tmp_path/"assistx-fleet.json"
    file.write_text(json.dumps(data))
    os.chmod(file,0o600)
    return file

def test_empty_inventory_is_reported_but_not_fabricated(tmp_path):
    row=inventory(private_file(tmp_path,fixture()))
    assert row["nodes"]==[] and row["models"]==[]
    assert row["source"]=="assistx_local_inventory"

def test_fleet_snapshot_stale_wrong_source_permissions_and_symlink_denied(tmp_path):
    file=private_file(tmp_path,fixture(now=datetime.now(timezone.utc)-timedelta(minutes=3)))
    with pytest.raises(ValueError,match="stale"):inventory(file)
    file=private_file(tmp_path,fixture())
    os.chmod(file,0o644)
    with pytest.raises(ValueError,match="untrusted"):inventory(file)
    os.chmod(file,0o600)
    alias=tmp_path/"alias.json"
    alias.symlink_to(file)
    with pytest.raises(OSError):inventory(alias)
    data=fixture()
    data["ip"]="100.11.12.13"
    with pytest.raises(ValueError):inventory(private_file(tmp_path,data))

def test_node_and_model_schema_enforced(tmp_path):
    n={"name":"xwing","models":["safe-model"],"inflight":2}
    m={"id":"safe-model","nodes":1}
    f=private_file(tmp_path,fixture(nodes=[n],models=[m]))
    assert inventory(f)["models"]==[m]
    n2=n | {"password":"LEAK"}
    with pytest.raises(ValueError):inventory(private_file(tmp_path,fixture(nodes=[n2],models=[m])))
    with pytest.raises(ValueError):inventory(private_file(tmp_path,fixture(
        nodes=[n],models=[m | {"endpoint":"100.22.33.44"}])))

def test_numeric_node_ip_denied_for_private_address_confidentiality(tmp_path):
    for address in ("192.168.1.12","10.0.0.2","172.17.0.1","100.11.22.33","::1"):
        node={"name":address,"models":[],"inflight":None}
        with pytest.raises(ValueError):
            inventory(private_file(tmp_path,fixture(nodes=[node])))


def test_publisher_filters_only_verified_metadata(tmp_path):
    class Result:
        returncode=0
        stdout=json.dumps(fixture(nodes=[{"name":"xwing","models":["safe-model"],"inflight":2}],
                                  models=[{"id":"safe-model","nodes":1}]))
    calls=[]
    def run(argv,**kw):
        calls.append(argv)
        assert argv[:4]==["docker","exec","-i","assistx-api"]
        assert "BASIC_AUTH_PASS" not in kw.get("input","")
        return Result()
    target=tmp_path/"state"/"assistx-fleet.json"
    assert refresh(run=run,destination=target)==(1,1)
    assert os.stat(target).st_mode & 0o777 == 0o600
    assert len(calls)==1
    assert inventory(target)["models"][0]["nodes"]==1
