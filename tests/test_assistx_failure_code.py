"""Publisher-side contract for the closed-enum AssistX failure code.

No raw reason text, no new producer fields, and no change to the five-scalar
per-record snapshot schema. The only addition is a closed-enum count map.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

# Import by directory path: an unrelated installed package named `scripts`
# otherwise shadows the repository's namespace package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from assistx_failure_code import (  # noqa: E402
    FAILURE_CODES, derive_failure_code, failure_code_counts,
    validate_counts, json_counts,
)
from refresh_assistx_trace_snapshot import refresh  # noqa: E402

SCALARS = ("correlation_id", "outcome", "events", "last_ts_ms", "duration_ms")
SENTINEL = "RAW-SECRET-REASON: auth failed for user@host /tmp/private"


def rec(outcome, events, duration, cid="c-1"):
    return {"correlation_id": cid, "outcome": outcome, "events": events,
            "last_ts_ms": 1790000000000, "duration_ms": duration}


class FakeResult:
    def __init__(self, stdout):
        self.returncode = 0
        self.stdout = stdout


class FailureCodeContract(unittest.TestCase):
    def test_every_enum_value_is_derivable(self):
        cases = [
            (rec("open", 1, 0), "ok"),
            (rec("completed", 1, 5), "ok"),
            (rec("failed", 0, 0), "no_events"),
            (rec("failed", 1, 0), "zero_duration"),
            (rec("failed", 2, 75), "elapsed"),
            (rec("failed", None, 0), "unknown"),
        ]
        for row, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(derive_failure_code(row), expected)
                self.assertIn(expected, FAILURE_CODES)
        self.assertEqual(set(FAILURE_CODES),
                         {"ok", "no_events", "zero_duration", "elapsed", "unknown"})

    def test_malformed_input_fails_closed_and_never_emits_raw_text(self):
        malformed = [
            None, "failed text", [], 7,
            {"outcome": "madeup", "events": 1, "duration_ms": 0},
            {"outcome": "failed", "events": True, "duration_ms": 0},
            {"outcome": "failed", "events": 1.0, "duration_ms": 0},
            {"outcome": "failed", "events": -1, "duration_ms": 0},
            {"outcome": "failed", "events": 1, "duration_ms": "0"},
            {"outcome": "failed", "events": 1},
            {"outcome": "failed", "events": 1, "duration_ms": 10 ** 13 + 1},
        ]
        for row in malformed:
            with self.subTest(row=repr(row)[:60]):
                self.assertEqual(derive_failure_code(row), "unknown")
        hostile = rec("failed", 1, 0, cid=SENTINEL)
        self.assertEqual(derive_failure_code(hostile), "zero_duration")
        self.assertNotIn(SENTINEL, json_counts(failure_code_counts([hostile])))
        self.assertIsNone(validate_counts({"reason": SENTINEL}))
        self.assertIsNone(validate_counts({"elapsed": -1}))
        self.assertIsNone(validate_counts({"elapsed": 26}))
        self.assertEqual(validate_counts({"zero_duration": 5}), {"zero_duration": 5})

    def test_counts_reconcile_and_are_aggregate_only(self):
        rows = [rec("open", 1, 0), rec("completed", 1, 5),
                rec("failed", 0, 0), rec("failed", 1, 0),
                rec("failed", 1, 0), rec("failed", 2, 75),
                rec("failed", None, 0)]
        counts = failure_code_counts(rows)
        self.assertEqual(counts,
                         {"elapsed": 1, "no_events": 1, "unknown": 1, "zero_duration": 2})
        failed = sum(row["outcome"] == "failed" for row in rows)
        self.assertEqual(sum(counts.values()), failed)
        self.assertEqual(counts, json.loads(json_counts(counts)))

    def test_refresh_keeps_five_scalar_schema_and_adds_only_aggregate(self):
        now = datetime.now(timezone.utc).isoformat()
        producer_rows = [
            {"correlation_id": "c-1", "outcome": "failed", "events": 1,
             "last_ts_ms": 1790000000000, "duration_ms": 0,
             "error": SENTINEL, "stack_trace": "RAW-STACK", "provider_key": "secret"},
            {"correlation_id": "c-2", "outcome": "open", "events": 3,
             "last_ts_ms": 1790000001000, "duration_ms": 42, "reason": "raw text"},
            {"correlation_id": "c-3", "outcome": "failed", "events": 0,
             "last_ts_ms": 1790000002000, "duration_ms": 0, "error": SENTINEL},
        ]
        payload = json.dumps({"source": "assistx_trace_index", "observed_at": now,
                              "traces": producer_rows})

        def fake_run(*args, **kwargs):
            return FakeResult(payload)

        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "nested" / "traces.json"
            self.assertEqual(refresh(run=fake_run, destination=dest), 3)
            raw = dest.read_bytes()
            for forbidden in (SENTINEL.encode(), b"stack_trace", b"provider_key", b"raw text"):
                self.assertNotIn(forbidden, raw)
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            data = json.loads(raw)
            self.assertEqual(set(data),
                             {"source", "observed_at", "traces", "failure_code_counts"})
            for row in data["traces"]:
                # Strict five-scalar schema expected by observer and importer.
                self.assertEqual(set(row.keys()), set(SCALARS))
            self.assertEqual(data["failure_code_counts"],
                             {"no_events": 1, "zero_duration": 1})


if __name__ == "__main__":
    unittest.main()
