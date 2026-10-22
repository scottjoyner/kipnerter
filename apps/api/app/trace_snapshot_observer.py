"""Read only the pre-sanitized local AssistX index snapshot. No Docker access."""
import json
import os
import pwd
import re
import stat
from pathlib import Path
from datetime import datetime, timezone, timedelta


def trace_path():
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/state/kipnerter-observer/traces.json"


def recent_traces(path=None, now=None):
    target = path or trace_path()
    if target.parent.is_symlink():
        raise ValueError("symlinked trace directory")
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        state = os.fstat(fd)
        if not stat.S_ISREG(state.st_mode) or state.st_size > 65536 or state.st_uid != os.getuid():
            raise ValueError("unsafe trace snapshot")
        if state.st_mode & 0o077:
            raise ValueError("trace snapshot permissions not private")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            body = stream.read(65537)
        if len(body) > 65536:
            raise ValueError("trace snapshot oversized")
    finally:
        if fd != -1:
            os.close(fd)
    record = json.loads(body)
    if not isinstance(record, dict) or record.get("source") != "assistx_trace_index":
        raise ValueError("invalid trace snapshot provenance")
    stamp = record.get("observed_at")
    if not isinstance(stamp,str):
        raise ValueError("missing trace observation time")
    try:
        observed = datetime.fromisoformat(stamp.replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("invalid trace observation time") from exc
    if observed.tzinfo is None:
        raise ValueError("naive trace timestamp")
    current = now or datetime.now(timezone.utc)
    if not current - timedelta(seconds=90) <= observed.astimezone(timezone.utc) <= current + timedelta(seconds=10):
        raise ValueError("trace snapshot not fresh")
    raw = record.get("traces")
    if not isinstance(raw, list) or len(raw) > 25:
        raise ValueError("invalid trace rows")
    traces = []
    for row in raw:
        if not isinstance(row,dict) or set(row.keys()) != {
                "correlation_id", "outcome", "events", "last_ts_ms", "duration_ms"}:
            raise ValueError("unexpected trace snapshot schema")
        if not isinstance(row["correlation_id"],str) or not re.fullmatch(
                r"[A-Za-z0-9_.:/-]{1,128}",row["correlation_id"]):
            raise ValueError("unsafe trace correlation id")
        if row["outcome"] not in ("open","completed","failed"):
            raise ValueError("invalid trace outcome")
        for key in ("events","last_ts_ms","duration_ms"):
            value = row[key]
            if value is not None and (type(value) is not int or not 0 <= value <= 10000000000000):
                raise ValueError("invalid trace scalar")
        traces.append({key:row[key] for key in (
            "correlation_id", "outcome", "events", "last_ts_ms", "duration_ms")})
    return {"source":"assistx_trace_index", "observed_at":stamp, "traces":traces}
