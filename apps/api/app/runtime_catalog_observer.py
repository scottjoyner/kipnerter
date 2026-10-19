"""One fixed read-only LM Studio loopback catalog probe; metadata only.

Never sends credentials, invokes a load/unload API, scans the tailnet, or
claims a catalog item is proven resident. Stored model file paths / API payload
are not returned. GET against a literal loopback native endpoint only.
"""
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone

URL = "http://127.0.0.1:1234/api/v1/models"
MAX_BYTES = 512_000
MAX_MODELS = 50
MAX_INSTANCES = 64

def _safe_display(value, identity):
    # Descriptive names may be user-controlled: never echo paths, URLs,
    # backslashes, control chars, emails, or unbounded freeform text.
    if (isinstance(value, str) and 1 <= len(value) <= 90
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._+():-]*", value)
            and ".." not in value):
        return value
    return "catalog-" + identity


def read_catalog(fetch=None, now=None):
    if fetch is None:
        def fetch():
            request = urllib.request.Request(
                URL, method="GET", headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=3) as response:
                if response.status != 200 or response.geturl() != URL:
                    raise ValueError("unexpected native runtime catalog response")
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("native catalog too large")
                return json.loads(raw)
    document = fetch()
    if not isinstance(document, dict) or not isinstance(document.get("models"), list):
        raise ValueError("malformed native runtime catalog")
    entries = document["models"]
    if len(entries) > 1000:
        raise ValueError("unbounded native runtime catalog")
    models = []
    for row in entries:
        if len(models) >= MAX_MODELS:
            break
        if not isinstance(row, dict):
            continue
        key = row.get("key")
        if not isinstance(key, str) or not 1 <= len(key) <= 1024:
            continue
        # Stable opaque ID, not a model path or repository identifier.
        model_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        instances = row.get("loaded_instances")
        if not isinstance(instances, list) or len(instances) > MAX_INSTANCES:
            continue
        kind = row.get("type")
        if kind not in ("llm", "embedding"):
            kind = "other"
        models.append({
            "id": "lmstudio-" + model_id,
            "name": _safe_display(row.get("display_name"), model_id),
            "kind": kind,
            "loaded_instances": len(instances),
            "runtime_reported_loaded": bool(instances),
            "independently_verified": False,
        })
    timestamp = now or datetime.now(timezone.utc)
    return {
        "source": "lmstudio_native_catalog",
        "observed_at": timestamp.isoformat(),
        "node": "x1-370",
        "models": models,
        "total_catalog_entries": len(entries),
        "snapshot_truncated": len(entries) > MAX_MODELS,
    }
