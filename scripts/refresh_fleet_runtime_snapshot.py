#!/usr/bin/env python3
"""Read-only fixed-host LM Studio inventory over pinned SSH host identities.

Never probes unknown fleet hosts, reads remote credentials, sends model prompts,
loads models, mutates processes, or asks runtimes to refresh discovery. Each
remote call reads only fixed localhost paths and emits numeric counts.
"""
import concurrent.futures
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile

HOSTS = ("xwing", "destroyer", "lenovo", "beelink", "deathstar", "optiplex")
MAX_BYTES = 32768
REMOTE = r'''
import json, urllib.request, urllib.error, pathlib
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw): return None
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
def read(endpoint, key):
    req = urllib.request.Request(endpoint, method="GET", headers={"Accept":"application/json"})
    try:
        with opener.open(req, timeout=2) as response:
            if response.status != 200 or response.geturl() != endpoint:
                return {"status":"unavailable"}
            raw=response.read(131073)
        if len(raw)>131072: return {"status":"unavailable"}
        data=json.loads(raw)
        models=data.get(key) if isinstance(data,dict) else None
        if not isinstance(models,list) or len(models)>1000:
            return {"status":"unavailable"}
        if key=="models":
            loaded=0
            for item in models:
                if not isinstance(item,dict):continue
                instances=item.get("loaded_instances",[])
                if not isinstance(instances,list) or len(instances)>64:
                    return {"status":"unavailable"}
                loaded+=len(instances)
            if loaded>256: return {"status":"unavailable"}
            return {"status":"reported", "catalog_entries":len(models), "loaded_instances":loaded}
        return {"status":"reported", "advertised_entries":len(models)}
    except Exception:
        return {"status":"unavailable"}
def process_count():
    try:
        count = 0
        for entry in pathlib.Path("/proc").iterdir():
            if not entry.name.isdigit(): continue
            try:
                if (entry/"comm").read_text().strip() == "llama-server":
                    count += 1
            except (OSError, UnicodeError): continue
        if count > 256: return {"status":"unavailable"}
        return {"status":"reported", "llama_server_count":count}
    except (OSError, UnicodeError): return {"status":"unavailable"}
print(json.dumps({"native":read("http://127.0.0.1:1234/api/v1/models","models"),
                  "openai":read("http://127.0.0.1:1234/v1/models","data"),
                  "processes":process_count()},separators=(",",":")))
'''

def sample_host(host, runner=None):
    if host not in HOSTS:
        raise ValueError("unapproved runtime observer target")
    runner = runner or subprocess.run
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=3", "-o", "ConnectionAttempts=1",
            "-o", "NumberOfPasswordPrompts=0", "-o", "ClearAllForwardings=yes",
            "-o", "ForwardAgent=no", "-T", host, "python3 -"]
    unavailable = {"status": "unavailable"}
    try:
        result = runner(argv, input=REMOTE, capture_output=True, text=True,
                        timeout=11, check=False)
    except (OSError, subprocess.SubprocessError):
        return {"node": host, "ssh": "unavailable", "native": unavailable,
                "openai": unavailable, "processes": unavailable,
                "model_binding":"unverified"}
    if result.returncode != 0 or len(result.stdout) > MAX_BYTES:
        return {"node": host, "ssh": "unavailable", "native": unavailable,
                "openai": unavailable, "processes": unavailable,
                "model_binding":"unverified"}
    try:
        data = json.loads(result.stdout)
        if not isinstance(data,dict) or set(data)!={"native","openai","processes"}:
            raise ValueError("wrong remote result fields")
        native, openai, processes = data["native"],data["openai"],data["processes"]
        for item, fields, bound in ((native,{"catalog_entries","loaded_instances"},256),
                                    (openai,{"advertised_entries"},1000),
                                    (processes,{"llama_server_count"},256)):
            if not isinstance(item,dict) or item.get("status") not in ("reported","unavailable"):
                raise ValueError("invalid runtime state")
            if item["status"]=="unavailable":
                if set(item)!={"status"}:raise ValueError("invalid unavailable payload")
            elif set(item)!=(fields|{"status"}):
                raise ValueError("invalid runtime counter fields")
            elif any(type(item[k]) is not int or not 0<=item[k]<=bound for k in fields):
                raise ValueError("invalid runtime count")
        return {"node":host, "ssh":"reported", "native":native, "openai":openai,
                "processes":processes, "model_binding":"unverified"}
    except (ValueError,TypeError,KeyError):
        return {"node":host, "ssh":"unavailable", "native":unavailable,
                "openai":unavailable, "processes":unavailable,
                "model_binding":"unverified"}

def snapshot_path():
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/state/kipnerter-observer/fleet-runtime.json"

def refresh(path=None, observer=sample_host, hosts=HOSTS, now=None):
    if tuple(hosts)!=HOSTS:
        raise ValueError("fleet runtime SSH allowlist cannot be expanded dynamically")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        rows=list(executor.map(observer,hosts))
    record={"source":"fleet_runtime_inventory",
            "observed_at":(now or datetime.now(timezone.utc)).isoformat(),"nodes":rows}
    # Whitelist again before persistence: remote output must never be used to
    # inject unapproved names, model paths, IPs, commands, or arbitrary fields.
    from_schema(record)
    target=path or snapshot_path()
    directory=target.parent
    if directory.is_symlink() or (target.exists() and target.is_symlink()):
        raise ValueError("unsafe runtime snapshot path")
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if directory.stat().st_uid!=os.getuid():raise ValueError("unowned runtime directory")
    directory.chmod(0o700)
    if target.exists() and (not target.is_file() or target.stat().st_uid!=os.getuid()):
        raise ValueError("untrusted runtime snapshot")
    fd,scratch=tempfile.mkstemp(prefix=".fleet-runtime-",dir=directory)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as output:
            os.fchmod(output.fileno(),0o600)
            json.dump(record,output,separators=(",",":"),allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(scratch,target)
    finally:
        if os.path.exists(scratch):os.unlink(scratch)
    return record

def from_schema(document):
    if not isinstance(document,dict) or set(document)!={"source","observed_at","nodes"}:
        raise ValueError("bad runtime snapshot keys")
    if document["source"]!="fleet_runtime_inventory":raise ValueError("bad source")
    if not isinstance(document["nodes"],list) or len(document["nodes"])!=len(HOSTS):
        raise ValueError("missing fixed witness hosts")
    for host,row in zip(HOSTS,document["nodes"]):
        if not isinstance(row,dict) or set(row)!={"node","ssh","native","openai","processes","model_binding"} or row["node"]!=host or row["ssh"] not in ("reported","unavailable") or row["model_binding"]!="unverified":
            raise ValueError("invalid fixed host witness")
        for kind,allowed,bound in (("native",{"catalog_entries","loaded_instances"},256),
                                   ("openai",{"advertised_entries"},1000),
                                   ("processes",{"llama_server_count"},256)):
            info=row[kind]
            if not isinstance(info,dict) or info.get("status") not in ("reported","unavailable"):
                raise ValueError("bad probe status")
            if info["status"]=="unavailable":
                if set(info)!={"status"}:raise ValueError("unknown unavailable fields")
            elif set(info)!=allowed|{"status"} or any(type(info[k]) is not int or not 0<=info[k]<=bound for k in allowed):
                raise ValueError("bad probe fields")
    return document

if __name__=="__main__":
    try:
        value=refresh()
        print("Fleet runtime metadata snapshot published; hosts=6")
    except (OSError,ValueError,subprocess.SubprocessError):
        raise SystemExit("Fleet runtime metadata unavailable; prior snapshot will expire")
