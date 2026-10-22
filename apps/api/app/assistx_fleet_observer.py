"""Validate a time-bounded local AssistX metadata-only inventory snapshot."""
import ipaddress
import json
import os
import pwd
import stat
from pathlib import Path
from datetime import datetime, timedelta, timezone
import re


def snapshot_path():
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return home / ".local/state/kipnerter-observer/assistx-fleet.json"


def inventory(path=None, now=None):
    target = path or snapshot_path()
    if target.parent.is_symlink():
        raise ValueError("symlinked AssistX inventory directory")
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        state = os.fstat(fd)
        if not stat.S_ISREG(state.st_mode) or state.st_uid != os.getuid() or state.st_size > 65536 or state.st_mode & 0o077:
            raise ValueError("untrusted AssistX snapshot")
        with os.fdopen(fd,"r",encoding="utf-8") as stream:
            fd=-1
            raw=stream.read(65537)
        if len(raw)>65536:raise ValueError("AssistX snapshot oversized")
    finally:
        if fd!=-1:os.close(fd)
    doc=json.loads(raw)
    if not isinstance(doc,dict) or set(doc) != {"source","observed_at","nodes","models"} or doc["source"]!="assistx_local_inventory":
        raise ValueError("invalid AssistX snapshot source")
    stamp=doc.get("observed_at")
    if not isinstance(stamp,str):raise ValueError("missing AssistX timestamp")
    observed=datetime.fromisoformat(stamp.replace("Z","+00:00"))
    current=now or datetime.now(timezone.utc)
    if observed.tzinfo is None or not current-timedelta(seconds=90)<=observed.astimezone(timezone.utc)<=current+timedelta(seconds=10):
        raise ValueError("stale AssistX snapshot")
    nodes=doc.get("nodes")
    models=doc.get("models")
    if not isinstance(nodes,list) or len(nodes)>50 or not isinstance(models,list) or len(models)>50:
        raise ValueError("AssistX snapshot has bad shape")
    for node in nodes:
        if not isinstance(node,dict) or set(node)!={"name","models","inflight"}:
            raise ValueError("unapproved node fields")
        if not isinstance(node["name"],str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,79}",node["name"]) or "://" in node["name"]:
            raise ValueError("bad node identifier")
        try: ipaddress.ip_address(node["name"])
        except ValueError: pass
        else: raise ValueError("numeric host address cannot be exported")
        if not isinstance(node["models"],list) or len(node["models"])>12 or any(
            not isinstance(model,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+ -]{0,119}",model)
            for model in node["models"]
        ):raise ValueError("bad node models")
        if node["inflight"] is not None and (
            type(node["inflight"]) is not int or not 0<=node["inflight"]<=100000
        ):raise ValueError("bad inflight")
    for model in models:
        if not isinstance(model,dict) or set(model)!={"id","nodes"}:
            raise ValueError("unapproved model fields")
        if not isinstance(model["id"],str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+ -]{0,119}",model["id"]):
            raise ValueError("bad model identifier")
        if type(model["nodes"]) is not int or not 0<=model["nodes"]<=100:
            raise ValueError("bad model count")
    return {"source":"assistx_local_inventory","observed_at":stamp,"nodes":nodes,"models":models}
