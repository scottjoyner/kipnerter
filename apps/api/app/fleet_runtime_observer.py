"""Validated read-only view of scheduled six-host runtime-probe receipts.

No SSH, service discovery, Docker access or dynamically selected endpoints.
"""
import json
import os
import pwd
import stat
from pathlib import Path
from datetime import datetime, timedelta, timezone

HOSTS = ("xwing", "destroyer", "lenovo", "beelink", "deathstar", "optiplex")


def _path():
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/state/kipnerter-observer/fleet-runtime.json"


def observations(path=None, now=None):
    target=path or _path()
    if target.parent.is_symlink():raise ValueError("symlinked fleet inventory directory")
    fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_size>32768 or st.st_mode & 0o077:
            raise ValueError("untrusted fleet runtime snapshot")
        with os.fdopen(fd,"r",encoding="utf-8") as f:
            fd=-1
            body=f.read(32769)
        if len(body)>32768:raise ValueError("runtime snapshot too large")
    finally:
        if fd!=-1:os.close(fd)
    data=json.loads(body)
    if not isinstance(data,dict) or set(data)!={"source","observed_at","nodes"} or data["source"]!="fleet_runtime_inventory":
        raise ValueError("invalid runtime source")
    stamp=data.get("observed_at")
    if not isinstance(stamp,str):raise ValueError("bad runtime timestamp")
    observed=datetime.fromisoformat(stamp.replace("Z","+00:00"))
    current=now or datetime.now(timezone.utc)
    if observed.tzinfo is None or not current-timedelta(seconds=90)<=observed.astimezone(timezone.utc)<=current+timedelta(seconds=10):
        raise ValueError("stale fleet runtime witness")
    rows=data["nodes"]
    if not isinstance(rows,list) or len(rows)!=len(HOSTS):
        raise ValueError("missing required fixed host evidence")
    for host,row in zip(HOSTS,rows):
        if not isinstance(row,dict) or set(row)!={"node","ssh","native","openai"} or row["node"]!=host or row["ssh"] not in ("reported","unavailable"):
            raise ValueError("unexpected runtime host")
        for kind,fields,bound in (("native",{"catalog_entries","loaded_instances"},256),
                                  ("openai",{"advertised_entries"},1000)):
            item=row[kind]
            if not isinstance(item,dict) or item.get("status") not in ("reported","unavailable"):
                raise ValueError("invalid runtime endpoint")
            if item["status"]=="unavailable":
                if set(item)!={"status"}:raise ValueError("leaked runtime response fields")
            elif set(item)!=fields|{"status"} or any(type(item[k]) is not int or not 0<=item[k]<=bound for k in fields):
                raise ValueError("unexpected runtime count")
    return data
