#!/usr/bin/env python3
"""Closed-enum AssistX failure-code derivation (metadata-only, fail-closed).

The five sanitized scalars (correlation_id, outcome, events, last_ts_ms,
duration_ms) are the only producer fields available on the host. This module
derives a small closed code set from those scalars alone:

  ok             outcome is open/completed (not a terminal failure)
  no_events      failed with events == 0 (failed before any event was kept)
  zero_duration  failed with events >= 1 and duration_ms == 0
  elapsed        failed with events >= 1 and duration_ms > 0
  unknown        failed, but a scalar needed for classification is absent or
                 malformed (fail closed)

No correlation identifier, timestamp text, error text, or any other producer
key is read or emitted. Semantic causes (auth / timeout / transport /
no_provider) are deliberately NOT encoded: they cannot be derived from the
available scalars, so labelling a failure with one would be a guess. Such
failures are reported as `unknown` rather than invented.
"""
import json

FAILURE_CODES = ("ok", "no_events", "zero_duration", "elapsed", "unknown")
FAILED_CODES = frozenset(FAILURE_CODES) - {"ok"}
MAX_COUNT = 10_000_000_000_000

# Deliberately no import of raw-text helpers, no regex over identifiers, and
# no reads of correlation_id / last_ts_ms. Only the two count scalars matter.


def _valid_count(value):
    """Reject bools, floats, negatives and out-of-range integers."""
    return type(value) is int and 0 <= value <= MAX_COUNT


def derive_failure_code(record):
    """Return exactly one of FAILURE_CODES. Total over any input; never raises.

    The function is intentionally independent of raw text: a correlation id
    full of hostile characters cannot influence the resulting code.
    """
    if not isinstance(record, dict):
        return "unknown"
    outcome = record.get("outcome")
    if outcome not in ("open", "completed", "failed"):
        return "unknown"
    if outcome != "failed":
        return "ok"
    events = record.get("events")
    duration = record.get("duration_ms")
    if not _valid_count(events) or not _valid_count(duration):
        return "unknown"
    if events == 0:
        return "no_events"
    if duration == 0:
        return "zero_duration"
    return "elapsed"


def failure_code_counts(records):
    """Count FAILED records by closed code; return only {code: int}.

    Non-failed records are ignored, so the sum always equals the number of
    failed records in the same window. No identifiers are returned.
    """
    if not isinstance(records, (list, tuple)):
        return {}
    counts = {}
    for record in records:
        if not isinstance(record, dict) or record.get("outcome") != "failed":
            continue
        code = derive_failure_code(record)
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def validate_counts(candidate, max_total=25):
    """Accept only a closed-enum, non-negative integer count map, else None.

    Used to sanity-check a producer-supplied aggregate so tampered or raw-text
    values can never be copied into the private index.
    """
    if not isinstance(candidate, dict):
        return None
    total = 0
    for code, value in candidate.items():
        if code not in FAILED_CODES or not _valid_count(value):
            return None
        total += value
    if total > max_total:
        return None
    return dict(sorted(candidate.items()))


def json_counts(counts):
    """Deterministic compact JSON for the aggregate meta value."""
    return json.dumps(counts, separators=(",", ":"), sort_keys=True)
