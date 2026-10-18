"""Project limited launcher job metadata; never expose prompts or raw agent transcripts."""
import json
import os
import pwd
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

JOB = re.compile(r"^job-[a-f0-9]{12}\.json$")
STATES = {"QUEUED", "RUNNING", "COMPLETED", "COMPLETED_UNVERIFIED", "FAILED", "TIMEOUT", "CANCELED", "START_FAILED"}
AGENTS = {"hermes", "opencode"}

def _state_dir():
    configured = os.environ.get("FLEET_AGENT_STATE_DIR")
    return Path(configured) if configured else Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/state/fleet-agent-launcher"

def sessions(limit=30):
    """Fail closed on unsafe or unreadable ledger entries rather than silently skipping."""
    directory = _state_dir()
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("agent ledger unavailable or unsafe")
    paths = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.name.startswith("job-"):
                continue
            if not JOB.fullmatch(entry.name) or not entry.is_file(follow_symlinks=False):
                raise ValueError("unsafe agent ledger entry")
            paths.append(entry.name)
            if len(paths) > 5000:
                raise ValueError("agent ledger exceeds observer bound")
    jobs = []
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in paths:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                st = os.fstat(handle)
                if not stat.S_ISREG(st.st_mode) or st.st_size > 65536:
                    raise ValueError("invalid ledger file")
                with os.fdopen(handle, "r", encoding="utf-8") as stream:
                    handle = -1
                    raw = stream.read(65537)
                if len(raw) > 65536:
                    raise ValueError("oversize ledger file")
                job = json.loads(raw)
            finally:
                if handle != -1:
                    os.close(handle)
            if not isinstance(job, dict) or not isinstance(job.get("id"), str) or job["id"] + ".json" != name:
                raise ValueError("mismatched agent ledger")
            if job.get("agent") not in AGENTS or job.get("status") not in STATES:
                raise ValueError("unexpected agent state")
            projected = {
                "id": job["id"], "agent": job["agent"], "status": job["status"],
                "model": str(job.get("model") or "")[:120],
                "created_utc": str(job.get("created_utc") or "")[:45],
                "ended_utc": str(job.get("ended_utc") or "")[:45],
                "model_verified": job.get("model_witness") == "VERIFIED",
                "archive_verified": job.get("offload_verified") is True,
                "harvest_hold": str(job.get("harvest_status") or "").startswith("BLOCKED"),
            }
            jobs.append(projected)
    finally:
        os.close(fd)
    jobs.sort(key=lambda row: row["created_utc"], reverse=True)
    return {"source": "fleet-agent-launcher", "observed_at": datetime.now(timezone.utc).isoformat(),
            "sessions": jobs[:max(1, min(int(limit), 50))], "total": len(jobs)}
