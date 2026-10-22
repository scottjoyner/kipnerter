#!/usr/bin/env python3
"""Extract sanitized AssistX fleet metadata using only existing local container auth.

No mutation, no rediscovery action, and no BasicAuth material leaves container.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import ipaddress
import json
import os
import pwd
import re
import stat
import subprocess
import tempfile

MAX_BYTES = 65536
SOURCE = r'''
import base64, datetime, ipaddress, json, os, re, urllib.request

username = os.getenv("BASIC_AUTH_USER")
password = os.getenv("BASIC_AUTH_PASS")
if not username or not password:
    raise SystemExit(3)
auth = base64.b64encode((username + ":" + password).encode()).decode()

def get(path):
    request = urllib.request.Request(
       "http://127.0.0.1:8000" + path,
       headers={"Authorization": "Basic " + auth, "Accept": "application/json"},
       method="GET")
    with urllib.request.urlopen(request, timeout=8) as r:
        if r.status != 200: raise SystemExit(4)
        content = r.read(500001)
    if len(content) > 500000: raise SystemExit(5)
    return json.loads(content)

def name(s, maxlen):
    return isinstance(s,str) and 0 < len(s) <= maxlen and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:/@+ -]*",s) is not None

def named_host(host):
    if not name(host,80) or "://" in host or any(c.isspace() for c in host):
        return False
    try: ipaddress.ip_address(host)
    except ValueError: return True
    return False

raw_nodes = get("/api/fleet/nodes")
raw_models = get("/api/fleet/models")
if not (isinstance(raw_nodes,dict) and isinstance(raw_nodes.get("nodes"),list)
        and isinstance(raw_models,dict) and isinstance(raw_models.get("models"),dict)):
    raise SystemExit(6)
nodes = []
for node in raw_nodes["nodes"][:50]:
    if not isinstance(node,dict): continue
    host = node.get("hostname")
    if not named_host(host): continue
    loaded = node.get("loaded_models")
    if not isinstance(loaded,list): loaded = []
    inflight = node.get("inflight")
    nodes.append({"name":host, "models":[m for m in loaded[:12] if name(m,120)],
                  "inflight": inflight if type(inflight) is int and 0 <= inflight <= 100000 else None})
models = []
for ident, value in list(raw_models["models"].items())[:50]:
    if not name(ident,120) or not isinstance(value,dict): continue
    reported_nodes = value.get("nodes")
    models.append({"id":ident, "nodes":min(len(reported_nodes),100) if isinstance(reported_nodes,list) else 0})
print(json.dumps({"source":"assistx_local_inventory",
    "observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "nodes":nodes,"models":models},separators=(",",":"),allow_nan=False))
'''

def snapshot_path():
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return home / ".local/state/kipnerter-observer/assistx-fleet.json"

def _validated(data):
    if not isinstance(data,dict) or set(data) != {"source","observed_at","nodes","models"}:
        raise ValueError("invalid AssistX fleet snapshot keys")
    if data["source"] != "assistx_local_inventory":
        raise ValueError("wrong AssistX fleet snapshot source")
    timestamp = datetime.fromisoformat(data["observed_at"].replace("Z","+00:00"))
    now = datetime.now(timezone.utc)
    if timestamp.tzinfo is None or not now-timedelta(seconds=90) <= timestamp <= now+timedelta(seconds=10):
        raise ValueError("invalid AssistX fleet snapshot timestamp")
    if not isinstance(data["nodes"],list) or len(data["nodes"]) > 50:
        raise ValueError("invalid AssistX fleet nodes")
    if not isinstance(data["models"],list) or len(data["models"]) > 50:
        raise ValueError("invalid AssistX model inventory")
    for node in data["nodes"]:
        if not isinstance(node,dict) or set(node) != {"name","models","inflight"}:
            raise ValueError("unapproved AssistX node fields")
        if (not isinstance(node["name"],str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,79}",node["name"])
                or "://" in node["name"]):
            raise ValueError("invalid host identifier")
        try: ipaddress.ip_address(node["name"])
        except ValueError: pass
        else: raise ValueError("numeric host address cannot be exported")
        if not isinstance(node["models"],list) or len(node["models"]) > 12:
            raise ValueError("invalid hosted model list")
        for model in node["models"]:
            if not isinstance(model,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+ -]{0,119}",model):
                raise ValueError("invalid hosted model")
        if node["inflight"] is not None and (
            type(node["inflight"]) is not int or not 0 <= node["inflight"] <= 100000
        ):
            raise ValueError("invalid inflight count")
    for model in data["models"]:
        if not isinstance(model,dict) or set(model) != {"id","nodes"}:
            raise ValueError("unapproved AssistX model fields")
        if not isinstance(model["id"],str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+ -]{0,119}",model["id"]):
            raise ValueError("invalid model identifier")
        if type(model["nodes"]) is not int or not 0 <= model["nodes"] <= 100:
            raise ValueError("invalid model node count")
    return data

def refresh(run=None, destination=None):
    run = run or subprocess.run
    result = run(["docker","exec","-i","assistx-api","python","-c",SOURCE],
                 input="",text=True,capture_output=True,timeout=25,check=False)
    if result.returncode != 0 or len(result.stdout) > MAX_BYTES:
        raise RuntimeError("AssistX fleet inventory collector unavailable")
    data = _validated(json.loads(result.stdout))
    directory = (destination or snapshot_path()).parent
    target = destination or snapshot_path()
    if directory.is_symlink():
        raise ValueError("unsafe AssistX snapshot directory")
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory.chmod(0o700)
    if target.is_symlink() or (target.exists() and not stat.S_ISREG(target.stat().st_mode)):
        raise ValueError("unsafe AssistX snapshot target")
    fd,temp = tempfile.mkstemp(prefix=".assistx-fleet-",dir=directory)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(data,stream,separators=(",",":"),allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp,target)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return len(data["nodes"]),len(data["models"])

if __name__ == "__main__":
    try:
        n,m=refresh()
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):
        raise SystemExit("AssistX metadata collector failed; old snapshot will expire")
    print(f"Published sanitized AssistX inventory: nodes={n} models={m}")
