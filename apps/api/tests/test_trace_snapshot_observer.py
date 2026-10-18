import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.trace_snapshot_observer import recent_traces


def _record(tmp_path, when=None, item=None):
    time = when or datetime.now(timezone.utc)
    path = tmp_path / "traces.json"
    path.write_text(json.dumps({
        "source": "assistx_trace_index",
        "observed_at": time.isoformat(),
        "traces": [item or {
            "correlation_id": "corr-123", "outcome": "completed",
            "events": 4, "last_ts_ms": 100, "duration_ms": 20,
        }],
    }))
    os.chmod(path, 0o600)
    return path


def test_sanitized_snapshot_requires_fresh_private_regular_file(tmp_path):
    path = _record(tmp_path)
    r = recent_traces(path)
    assert r["source"] == "assistx_trace_index"
    assert r["traces"][0]["correlation_id"] == "corr-123"
    assert set(r["traces"][0]) == {
        "correlation_id", "outcome", "events", "last_ts_ms", "duration_ms",
    }
    os.chmod(path, 0o644)
    with pytest.raises(ValueError):
        recent_traces(path)


def test_snapshot_stale_future_and_symlink_denied(tmp_path):
    now = datetime.now(timezone.utc)
    stale = _record(tmp_path, now-timedelta(minutes=3))
    with pytest.raises(ValueError):
        recent_traces(stale, now)
    future = _record(tmp_path, now+timedelta(minutes=2))
    with pytest.raises(ValueError):
        recent_traces(future, now)
    future.unlink()
    actual = _record(tmp_path)
    alias = tmp_path / "alias.json"
    alias.symlink_to(actual)
    with pytest.raises(OSError):
        recent_traces(alias)


def test_snapshot_rejects_non_allowlisted_fields_and_bad_identifiers(tmp_path):
    item = {
        "correlation_id": "corr-123", "outcome": "completed",
        "events": 4, "last_ts_ms": 100, "duration_ms": 20,
        "raw_prompt": "DO_NOT_EXPORT",
    }
    path = _record(tmp_path, item=item)
    with pytest.raises(ValueError):
        recent_traces(path)
    del item["raw_prompt"]
    item["correlation_id"] = "private secret"
    path = _record(tmp_path, item=item)
    with pytest.raises(ValueError):
        recent_traces(path)


def test_trace_publisher_never_exports_container_credentials(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from scripts.refresh_assistx_trace_snapshot import refresh

    class Result:
        returncode = 0
        stdout = json.dumps({
            "source": "assistx_trace_index",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "traces": [{
                "correlation_id": "corr-456", "outcome": "failed",
                "events": 8, "last_ts_ms": 111, "duration_ms": 22,
            }],
        })
    called = []
    def fake_run(argv, **kwargs):
        called.append(argv)
        assert argv[:4] == ["docker", "exec", "-i", "assistx-api"]
        assert kwargs.get("timeout") == 20
        return Result()
    path = tmp_path / "private" / "traces.json"
    assert refresh(run=fake_run, destination=path) == 1
    record = recent_traces(path)
    assert record["traces"][0]["outcome"] == "failed"
    assert "BASIC_AUTH_PASS" not in path.read_text()
    assert len(called) == 1



def test_trace_publisher_scrubs_unexpected_top_level_and_row_fields(tmp_path):
    from scripts.refresh_assistx_trace_snapshot import refresh
    class Result:
        returncode = 0
        stdout = json.dumps({
            "source": "assistx_trace_index",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "raw_transcript": "NEVER_WRITE_THIS",
            "traces": [{
                "correlation_id": "corr-456", "outcome": "failed",
                "events": 8, "last_ts_ms": 111, "duration_ms": 22,
                "internal_secret": "PRIVATE_PAYLOAD",
            }],
        })
    target = tmp_path / "private" / "traces.json"
    assert refresh(run=lambda *a, **kw: Result(), destination=target) == 1
    blob = target.read_text()
    assert "NEVER_WRITE_THIS" not in blob
    assert "PRIVATE_PAYLOAD" not in blob
    assert recent_traces(target)["traces"][0]["outcome"] == "failed"
