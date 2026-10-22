#!/usr/bin/env python3
"""Local-only scheduled AssistX trace-metadata snapshot.

The privileged Docker command runs only in the scheduled one-shot publisher,
never from the HTTP observer. No credentials, transcripts or event payloads
cross the container boundary. Snapshot is replace-only, never a raw archive.
"""
import json
import os
import pwd
import re
from datetime import datetime, timezone, timedelta
import stat
import subprocess
import tempfile
from pathlib import Path

MAX_BYTES = 65536
CONTAINER = "assistx-api"
SOURCE = r'''
import base64, datetime, json, os, re, urllib.request
u = os.environ.get("BASIC_AUTH_USER")
p = os.environ.get("BASIC_AUTH_PASS")
if not u or not p: raise SystemExit(3)
basic = base64.b64encode((u + ":" + p).encode()).decode("ascii")
request = urllib.request.Request(
  "http://127.0.0.1:8000/api/traces?limit=25&offset=0",
  headers={"Authorization": "Basic " + basic, "Accept": "application/json"},
  method="GET",
)
with urllib.request.urlopen(request, timeout=10) as r:
  if r.status != 200: raise SystemExit(4)
  body = r.read(500001)
if len(body) > 500000: raise SystemExit(5)
obj = json.loads(body)
if not isinstance(obj, dict) or not isinstance(obj.get("traces"), list):
  raise SystemExit(6)
rows = []
for t in obj["traces"][:25]:
  if not isinstance(t,dict): continue
  cid = t.get("correlation_id")
  outcome = t.get("outcome")
  if not isinstance(cid,str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}",cid):
    continue
  if outcome not in ("open","completed","failed"): continue
  row = {"correlation_id":cid, "outcome":outcome}
  for field in ("events","last_ts_ms","duration_ms"):
    value = t.get(field)
    row[field] = value if type(value) is int and 0 <= value <= 10000000000000 else None
  rows.append(row)
result = {"source":"assistx_trace_index",
 "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "traces": rows}
print(json.dumps(result,separators=(",",":"),allow_nan=False))
'''

def snapshot_path():
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return home / ".local/state/kipnerter-observer/traces.json"

def refresh(run=None, destination=None):
    run = run or subprocess.run
    result = run(
        ["docker", "exec", "-i", CONTAINER, "python", "-c", SOURCE],
        input="", text=True, capture_output=True, timeout=20, check=False,
    )
    if result.returncode != 0 or len(result.stdout) > MAX_BYTES:
        raise RuntimeError("trace index source unavailable")
    data = json.loads(result.stdout)
    if not isinstance(data,dict) or data.get("source") != "assistx_trace_index":
        raise ValueError("unexpected trace index projection")
    stamp = data.get("observed_at")
    try:
        ts = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None or not now - timedelta(seconds=90) <= ts <= now + timedelta(seconds=10):
            raise ValueError("trace index source timestamp invalid")
    except (AttributeError, TypeError) as exc:
        raise ValueError("trace index source timestamp invalid") from exc
    rows = data.get("traces")
    if not isinstance(rows,list) or len(rows) > 25:
        raise ValueError("unexpected trace index rows")
    sanitized = []
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get("correlation_id"),str) or not re.fullmatch(
                r"[A-Za-z0-9_.:/-]{1,128}",row["correlation_id"]):
            raise ValueError("invalid trace metadata")
        if row.get("outcome") not in ("open","completed","failed"):
            raise ValueError("invalid trace outcome")
        safe = {"correlation_id":row["correlation_id"], "outcome":row["outcome"]}
        for key in ("events","last_ts_ms","duration_ms"):
            value = row.get(key)
            if value is not None and (type(value) is not int or not 0 <= value <= 10000000000000):
                raise ValueError("invalid trace count")
            safe[key] = value
        sanitized.append(safe)
    # Defense in depth: discard every other producer key before disk write.
    data = {"source":"assistx_trace_index", "observed_at":ts.isoformat(),
            "traces":sanitized}
    target = destination or snapshot_path()
    directory = target.parent
    if directory.is_symlink():
        raise ValueError("trace directory is a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    if target.is_symlink() or (target.exists() and not stat.S_ISREG(target.stat().st_mode)):
        raise ValueError("unsafe snapshot target")
    fd, temp = tempfile.mkstemp(prefix=".traces-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(data,stream,separators=(",",":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp,target)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    return len(data["traces"])

if __name__ == "__main__":
    try:
        count = refresh()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        raise SystemExit("Trace metadata snapshot failed; previous data remains stale")
    print(f"Published {count} sanitized trace-index receipts")
