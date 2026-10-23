from pathlib import Path
import json
import os
import stat
from datetime import datetime, timezone

RECEIPT = Path("/home/scott/.local/state/kipnerter-preview-promotions/ee93905/status.json")
SHA = "ee93905bea286a18c9a10d5704068e6be5c86604"
TRUE_FIELDS = ("api_image_verified", "web_image_verified", "deployed_sha_matches",
               "funnel_disabled", "private_route_correct", "rollback_available")
FALSE_FIELDS = ("auth_qualified", "production_release_authorized", "production_modified")
CODE_FIELDS = {"chat_http": 200, "release_http": 200,
               "auth_session_http": 503, "rollback_http": 200}

def projection(path=RECEIPT, *, now=None):
    """Bearer-protected observer calls this only after authorization."""
    fd=os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o077 or not 0 < info.st_size <= 8192:
            raise ValueError("unsafe receipt")
        raw=os.read(fd, 8193)
    finally:
        os.close(fd)
    if len(raw)>8192:
        raise ValueError("oversized receipt")
    data=json.loads(raw)
    if not isinstance(data,dict) or not isinstance(data.get("checked_utc"),str):
        raise ValueError("invalid receipt")
    seen=datetime.fromisoformat(data["checked_utc"].replace("Z","+00:00"))
    if seen.tzinfo is None or seen.utcoffset().total_seconds()!=0:
        raise ValueError("non-UTC observation")
    age=((now or datetime.now(timezone.utc))-seen).total_seconds()
    if not -90 <= age <= 900:
        raise ValueError("stale receipt")
    if any(data.get(k) is not True for k in TRUE_FIELDS) or any(data.get(k) is not False for k in FALSE_FIELDS):
        raise ValueError("health or authorization drift")
    if any(type(data.get(k)) is not int or data[k]!=v for k,v in CODE_FIELDS.items()):
        raise ValueError("unexpected HTTP classification")
    if data.get("private_preview_status")!="ONLINE_AUTH_BLOCKED" or data.get("scope")!="private_tailnet_preview":
        raise ValueError("wrong scope/state")
    return {"source":"x1-370-immutable-private-preview","revision":SHA,
            "observed_at":seen.isoformat(),"age_seconds":int(max(0,age)),
            "deployment":"ONLINE_AUTH_BLOCKED","auth_qualified":False,
            "rollback_available":True,"funnel_enabled":False,
            "production_release_authorized":False}
