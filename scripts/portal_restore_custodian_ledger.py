#!/usr/bin/env python3
"""Local-only compare-and-append prototype for verified synthetic restore tips.

OS fsync and a hash chain demonstrate crash/concurrent-writer handling, NOT
rollback-resistant, independently administered external high-water custody.
Never use this log to authorize a production restore or deployment.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

if __package__:
    from .portal_restore_high_water import verify_high_water
    from .portal_restore_evidence import _canonical, _unique_json
else:
    from portal_restore_high_water import verify_high_water
    from portal_restore_evidence import _canonical, _unique_json

HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
ZERO = "0" * 64
MAX_LOG_BYTES = 1 << 20
MAX_RECORDS = 1024
REQUIRED = {
    "version", "scope", "end_sequence", "end_sha256",
    "signed_tip_sha256", "release_sha", "topology_sha256",
    "previous_checkpoint_sha256", "prior_record_sha256",
}


def _record_digest(record):
    return hashlib.sha256(_canonical(record)).hexdigest()


def _validate_log(raw):
    if len(raw) > MAX_LOG_BYTES or raw and not raw.endswith(b"\n"):
        raise ValueError("custodian research log truncated or oversized")
    lines = raw.splitlines()
    if len(lines) > MAX_RECORDS:
        raise ValueError("custodian research log exceeds record cap")
    records = []
    previous = ZERO
    for line in lines:
        if not line or len(line) > 2048:
            raise ValueError("oversized or empty custodian log entry")
        record = _unique_json(line.decode("utf-8", "strict"))
        if not isinstance(record, dict) or set(record) != REQUIRED or (
            type(record["version"]) is not int or record["version"] != 1 or
            record["scope"] != "synthetic_local_research_custodian" or
            type(record["end_sequence"]) is not int or
            not 2 <= record["end_sequence"] <= 2**53 or
            not all(type(record[k]) is str and HEX64.fullmatch(record[k]) for k in (
                "end_sha256", "signed_tip_sha256",
                "topology_sha256", "previous_checkpoint_sha256", "prior_record_sha256")) or
            type(record["release_sha"]) is not str or
            not HEX40.fullmatch(record["release_sha"])
        ):
            raise ValueError("malformed custodian research record")
        if record["prior_record_sha256"] != previous:
            raise ValueError("custodian research ledger record hash chain broken")
        if records:
            prior = records[-1]
            if (record["end_sequence"] != prior["end_sequence"] + 1 or
                record["previous_checkpoint_sha256"] != prior["end_sha256"] or
                record["release_sha"] != prior["release_sha"] or
                record["topology_sha256"] != prior["topology_sha256"]):
                raise ValueError("custodian research ledger rollback/fork")
        previous = _record_digest(record)
        records.append(record)
    return records, previous


def _open_log(directory, name, *, create):
    path = Path(directory)
    if (not isinstance(name, str) or name in ("", ".", "..") or
        "/" in name or "\\" in name or len(name) > 120):
        raise ValueError("unsafe custodian log name")
    dirfd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        folder = os.fstat(dirfd)
        if (folder.st_uid != os.getuid() or
            not stat.S_ISDIR(folder.st_mode) or folder.st_mode & 0o077):
            raise ValueError("custodian research directory must be owner-private")
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        if create:
            try:
                fd = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dirfd)
                os.fsync(dirfd)  # Only filesystem directory durability, not outside custody.
            except FileExistsError:
                fd = os.open(name, flags, dir_fd=dirfd)
        else:
            fd = os.open(name, flags, dir_fd=dirfd)
        try:
            status = os.fstat(fd)
            if (not stat.S_ISREG(status.st_mode) or status.st_uid != os.getuid() or
                status.st_mode & 0o077 or status.st_nlink != 1 or
                status.st_size > MAX_LOG_BYTES):
                raise ValueError("custodian research file must be private regular single-link")
            return dirfd, fd
        except BaseException:
            os.close(fd)
            raise
    except BaseException:
        os.close(dirfd)
        raise


def _loaded(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.read(fd, MAX_LOG_BYTES + 1)
    return _validate_log(raw)


def inspect_local_log(directory, name="synthetic-high-water.jsonl", *, expected_cursor):
    if type(expected_cursor) is not str or not HEX64.fullmatch(expected_cursor):
        raise ValueError("external cursor must be explicitly supplied")
    dfd, fd = _open_log(directory, name, create=False)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        records, cursor = _loaded(fd)
        if cursor != expected_cursor:
            raise ValueError("local custodian research ledger disagrees with external cursor")
        return {
            "count": len(records),
            "cursor_sha256": cursor,
            "cursor_matches_supplied_external": True,
            "latest_sequence": records[-1]["end_sequence"] if records else None,
            "source": "local_synthetic_research_ledger",
            "independent_custody_verified": False,
            "rollback_resistant_persistence_verified": False,
            "production_recovery_approved": False,
        }
    finally:
        os.close(fd)
        os.close(dfd)


def append_verified_tip(directory, *, chain, anchor, roles, observer,
                        signed_tip, custodian_trust, expected_cursor,
                        bootstrap_expected=None, name="synthetic-high-water.jsonl"):
    """Append only after verifying fourth key and exact caller-pinned old cursor.

    Bootstrap requires *separately supplied* (sequence, tip-digest) equality.
    Same-admin deletion of entire log+cursor is still not detectable.
    """
    verified = verify_high_water(chain, anchor, roles, observer, signed_tip, custodian_trust)
    if type(expected_cursor) is not str or not HEX64.fullmatch(expected_cursor):
        raise ValueError("missing externally retained cursor")
    dfd, fd = _open_log(directory, name, create=True)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        records, cursor = _loaded(fd)
        if cursor != expected_cursor:
            raise ValueError("stale optimistic cursor or changed local ledger")
        sequence = verified["end_sequence"]
        digest = verified["end_sha256"]
        previous_checkpoint = chain["entries"][-1]["checkpoint"]["payload"]["previous_checkpoint_sha256"]
        if records:
            prior = records[-1]
            if (sequence != prior["end_sequence"] + 1 or
                previous_checkpoint != prior["end_sha256"] or
                anchor["release_sha"] != prior["release_sha"] or
                anchor["topology_sha256"] != prior["topology_sha256"]):
                raise ValueError("replayed, forked or skipped verified checkpoint")
        elif (bootstrap_expected != (sequence, digest) or
              expected_cursor != ZERO):
            raise ValueError("first tip requires independently selected bootstrap pin")
        if len(records) >= MAX_RECORDS:
            raise ValueError("local custodian research log record cap reached")
        record = {
            "version": 1, "scope": "synthetic_local_research_custodian",
            "end_sequence": sequence, "end_sha256": digest,
            "signed_tip_sha256": verified["signed_tip_sha256"],
            "release_sha": anchor["release_sha"],
            "topology_sha256": anchor["topology_sha256"],
            "previous_checkpoint_sha256": previous_checkpoint,
            "prior_record_sha256": cursor,
        }
        encoded = _canonical(record) + b"\n"
        if os.fstat(fd).st_size + len(encoded) > MAX_LOG_BYTES:
            raise ValueError("local custodian research log full")
        os.lseek(fd, 0, os.SEEK_END)
        if os.write(fd, encoded) != len(encoded):
            raise OSError("incomplete append; manual incident review required")
        os.fsync(fd)
        return {
            "source": "local_synthetic_research_ledger",
            "appended_sequence": sequence,
            "cursor_sha256": _record_digest(record),
            "record_count": len(records) + 1,
            "four_key_tip_verified": True,
            "rollback_resistant_persistence_verified": False,
            "independent_custody_verified": False,
            "production_recovery_approved": False,
        }
    finally:
        os.close(fd)
        os.close(dfd)
