import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
import pytest

from app.fleet_runtime_observer import observations,HOSTS
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from scripts.refresh_fleet_runtime_snapshot import refresh, sample_host

EMPTY={"status":"unavailable"}

def rows():
    return [{"node":host,"ssh":"reported","native":dict(EMPTY),"openai":dict(EMPTY)}
            for host in HOSTS]

def record(when=None):
    return {"source":"fleet_runtime_inventory",
            "observed_at":(when or datetime.now(timezone.utc)).isoformat(),
            "nodes":rows()}

def private_file(path, data):
    path.write_text(json.dumps(data))
    os.chmod(path,0o600)
    return path

def test_read_only_allowlisted_host_with_bounded_probe_and_no_model_payload():
    class Result:
        returncode=0
        stdout=json.dumps({"native":{"status":"reported","catalog_entries":11,"loaded_instances":1},
                           "openai":{"status":"reported","advertised_entries":11}})
    def fake_run(args, **kwargs):
        assert args[0]=='ssh' and args[-2]=='beelink' and args[-1]=='python3 -'
        assert 'StrictHostKeyChecking=yes' in args
        assert 'BatchMode=yes' in args
        assert kwargs['timeout']==11
        text=kwargs['input']
        assert 'load_model' not in text and 'POST' not in text
        return Result()
    row=sample_host('beelink',fake_run)
    assert row['native']=={"status":"reported","catalog_entries":11,"loaded_instances":1}
    assert 'models' not in row
    with pytest.raises(ValueError):sample_host('arbitrary-remote-host',fake_run)

def test_ssh_failure_never_invents_available_model():
    def fail(*a, **kw):raise subprocess.TimeoutExpired(cmd='ssh', timeout=11)
    row=sample_host('xwing',fail)
    assert row['ssh']=='unavailable'
    assert row['native']==EMPTY
    assert row['openai']==EMPTY

def test_secure_snapshot_and_stale_reading(tmp_path):
    target=tmp_path/'state'/'fleet-runtime.json'
    value=refresh(path=target,observer=lambda name: next(row for row in rows() if row['node']==name))
    assert len(value['nodes'])==6
    assert os.stat(target).st_mode & 0o777 == 0o600
    assert observations(target)['nodes']==value['nodes']
    original=record(datetime.now(timezone.utc)-timedelta(minutes=2))
    with pytest.raises(ValueError,match='stale'):
        observations(private_file(target,original))
    private_file(target,record())
    os.chmod(target,0o644)
    with pytest.raises(ValueError,match='untrusted'):
        observations(target)
    alias=tmp_path/'pointer'
    alias.symlink_to(target)
    with pytest.raises(OSError):observations(alias)

def test_wrong_host_or_unexpected_raw_fields_denied(tmp_path):
    target=tmp_path/'fleet.json'
    altered=record()
    altered['nodes'][0]['node']='arbitrary'
    with pytest.raises(ValueError):observations(private_file(target,altered))
    altered=record()
    altered['nodes'][0]['native']={'status':'reported','catalog_entries':2,'loaded_instances':1,
                                   'model_path':'/home/private/sensitive.gguf'}
    with pytest.raises(ValueError):observations(private_file(target,altered))
    altered=record()
    altered['nodes'][0]['openai']={'status':'reported','advertised_entries':True}
    with pytest.raises(ValueError):observations(private_file(target,altered))


def test_api_reports_offhost_ssh_counts_but_never_infers_admission(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import control_plane
    monkeypatch.setenv('KIPNERTER_GATEWAY_TOKEN','synthetic-key')
    now=datetime.now(timezone.utc).isoformat()
    async def observe(path='/v1/nodes'):
        if path=='/v1/assistx-fleet':return {'source':'assistx_local_inventory','observed_at':now,'nodes':[],'models':[]}
        if path=='/v1/runtime-catalog':return {'source':'lmstudio_native_catalog','observed_at':now,'models':[]}
        assert path=='/v1/fleet-runtime'
        data=record()
        data['nodes'][3]['native']={'status':'reported','catalog_entries':11,'loaded_instances':1}
        data['nodes'][3]['openai']={'status':'reported','advertised_entries':11}
        return data
    monkeypatch.setattr(control_plane,'_tailscale_read',observe)
    response=TestClient(app).get('/api/v1/control-plane/models',headers={
        'Authorization':'Bearer synthetic-key'})
    assert response.status_code==200
    value=response.json()
    assert value['fleet_runtime_status']=='reported'
    assert value['assistx_status']=='reported_empty'
    beelink=value['fleet_runtime_nodes'][3]
    assert beelink['node']=='beelink' and beelink['native']['loaded_instances']==1
    assert value['models']==[] # no attempt to map unverified remote instance to routed model
    assert '/home/private/' not in str(value)
