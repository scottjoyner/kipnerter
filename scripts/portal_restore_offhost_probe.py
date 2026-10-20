#!/usr/bin/env python3
"""Read-only SSH probe of synthetic high-water ledger; NOT a custodian service.

Transmits only synthetic research JSONL and a random challenge to a fixed
known host over host-key-checked SSH. No remote disk writes or private keys.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess

if __package__:
    from .portal_restore_custodian_ledger import (
        _open_log, _loaded, HEX64, MAX_LOG_BYTES, ZERO,
    )
    from .portal_restore_evidence import _canonical
else:
    from portal_restore_custodian_ledger import _open_log, _loaded, HEX64, MAX_LOG_BYTES, ZERO
    from portal_restore_evidence import _canonical

HOST = "lenovo"
MAX_RESPONSE = 1024
# A separate stdlib implementation executed from memory: no code installation,
# writes, imported project tree, production data or SSH command from the caller.
REMOTE_PROGRAM = r"""
import base64, hashlib, json, re, socket, sys
def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate field")
        result[key] = value
    return result
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")
try:
    request = sys.stdin.buffer.read(1500000)
    if not request or len(request) >= 1500000: raise ValueError("oversized request")
    payload = json.loads(request, object_pairs_hook=unique)
    if not isinstance(payload, dict) or set(payload) != {"challenge", "cursor", "ledger"}:
        raise ValueError("invalid request shape")
    challenge, wanted = payload["challenge"], payload["cursor"]
    if type(challenge) is not str or not re.fullmatch("[a-f0-9]{64}", challenge):
        raise ValueError("invalid challenge")
    if type(wanted) is not str or not re.fullmatch("[a-f0-9]{64}", wanted):
        raise ValueError("invalid pinned cursor")
    raw = base64.b64decode(payload["ledger"], validate=True)
    if not 0 < len(raw) <= 1048576 or not raw.endswith(b"\n"):
        raise ValueError("invalid ledger bytes")
    entries = raw.splitlines()
    if not 1 <= len(entries) <= 1024: raise ValueError("too many ledger entries")
    previous = "0"*64
    sequence = None
    checkpoint_hash = None
    release = None
    topology = None
    required = {"version", "scope", "end_sequence", "end_sha256", "signed_tip_sha256",
      "release_sha", "topology_sha256", "previous_checkpoint_sha256",
      "prior_record_sha256"}
    hex64 = re.compile("[a-f0-9]{64}\Z")
    hex40 = re.compile("[a-f0-9]{40}\Z")
    for line in entries:
        if len(line) > 2048: raise ValueError("line oversized")
        r = json.loads(line, object_pairs_hook=unique)
        if (not isinstance(r, dict) or set(r) != required or
            type(r["version"]) is not int or r["version"] != 1 or
            r["scope"] != "synthetic_local_research_custodian" or
            type(r["end_sequence"]) is not int or
            not 2 <= r["end_sequence"] <= 2**53 or
            any(type(r[k]) is not str or not hex64.fullmatch(r[k]) for k in
                ("end_sha256", "signed_tip_sha256", "topology_sha256",
                 "previous_checkpoint_sha256", "prior_record_sha256")) or
            type(r["release_sha"]) is not str or not hex40.fullmatch(r["release_sha"]) or
            r["prior_record_sha256"] != previous):
            raise ValueError("invalid or forked record")
        if sequence is not None and (
            r["end_sequence"] != sequence+1 or
            r["previous_checkpoint_sha256"] != checkpoint_hash or
            r["release_sha"] != release or r["topology_sha256"] != topology):
            raise ValueError("discontinuous ledger")
        previous = hashlib.sha256(canonical(r)).hexdigest()
        sequence = r["end_sequence"]
        checkpoint_hash = r["end_sha256"]
        release = r["release_sha"]
        topology = r["topology_sha256"]
    if previous != wanted: raise ValueError("external cursor does not match ledger")
    result = {"challenge": challenge, "cursor_sha256": previous,
              "end_sequence": sequence, "record_count": len(entries),
              "host": socket.gethostname(), "recomputed_from_synthetic_bytes": True}
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
except (ValueError, TypeError, KeyError, UnicodeError) as exc:
    sys.stderr.write("HOLD: off-host synthetic cursor mismatch\n")
    sys.exit(2)
"""


def read_locked_synthetic_ledger(directory, name="synthetic-high-water.jsonl"):
    dirfd, fd = _open_log(directory, name, create=False)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        records, cursor = _loaded(fd)
        if not records:
            raise ValueError("empty synthetic ledger")
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, MAX_LOG_BYTES + 1)
        if not raw or len(raw) > MAX_LOG_BYTES:
            raise ValueError("invalid ledger bytes")
        return raw, cursor, records[-1]["end_sequence"], len(records)
    finally:
        os.close(fd)
        os.close(dirfd)


def probe(directory, expected_cursor, *, host=HOST, runner=subprocess.run,
          snapshot_reader=read_locked_synthetic_ledger):
    if host != HOST:
        raise ValueError("only prequalified host alias 'lenovo' is permitted")
    if type(expected_cursor) is not str or not HEX64.fullmatch(expected_cursor):
        raise ValueError("independently retained cursor required")
    raw, actual, sequence, count = snapshot_reader(directory)
    if actual != expected_cursor:
        raise ValueError("local snapshot differs from external cursor")
    challenge = secrets.token_hex(32)
    request = _canonical({"challenge": challenge, "cursor": expected_cursor,
                          "ledger": base64.b64encode(raw).decode("ascii")})
    if len(request) >= 1500000:
        raise ValueError("oversized synthetic probe request")
    cmd = ["ssh", "-T", "-o", "BatchMode=yes",
           "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=6",
           "-o", "ClearAllForwardings=yes", "-o", "RequestTTY=no",
           "--", HOST, "python3 -c " + shlex.quote(REMOTE_PROGRAM)]
    returned = runner(cmd, input=request, stdout=subprocess.PIPE,
                      stderr=subprocess.DEVNULL, timeout=16, check=False)
    if returned.returncode or len(returned.stdout) > MAX_RESPONSE:
        raise ValueError("host-key checked remote cursor verification unavailable")
    try:
        data = json.loads(returned.stdout)
    except (ValueError, UnicodeError):
        raise ValueError("remote response malformed") from None
    if (not isinstance(data, dict) or set(data) != {
            "challenge", "cursor_sha256", "end_sequence", "record_count",
            "host", "recomputed_from_synthetic_bytes"} or
        data["challenge"] != challenge or
        data["cursor_sha256"] != expected_cursor or
        type(data["end_sequence"]) is not int or data["end_sequence"] != sequence or
        type(data["record_count"]) is not int or data["record_count"] != count or
        data["recomputed_from_synthetic_bytes"] is not True or
        type(data["host"]) is not str or
        not 1 <= len(data["host"]) <= 128):
        raise ValueError("remote challenge, cursor or result mismatch")
    return {
        "source": "read_only_offhost_synthetic_cursor_probe",
        "remote_host": data["host"],
        "record_count": count,
        "end_sequence": sequence,
        "expected_cursor_matched": True,
        "remote_memory_only_compute": True,
        "remote_persistence_verified": False,
        "independent_administrative_custody_verified": False,
        "rollback_resistant_high_water_verified": False,
        "real_restore_verified": False,
        "production_recovery_approved": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-ledger-directory", required=True)
    parser.add_argument("--expected-cursor", required=True)
    args = parser.parse_args()
    try:
        result = probe(args.synthetic_ledger_directory, args.expected_cursor)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        raise SystemExit("RELEASE HOLD: read-only offhost probe failed: " + str(exc)) from None
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
