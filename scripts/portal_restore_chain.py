#!/usr/bin/env python3
"""Offline chain verifier for synthetic restore checkpoints, never a restore.

The start/end hashes and release/topology pins must come from a distinct,
operator-held file. Validating those pins does not prove that its custody is
independent, monotonic or rollback resistant.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess

if __package__:
    from .portal_restore_checkpoint import verify_checkpoint
    from .portal_restore_evidence import _canonical, _unique_json
else:
    from portal_restore_checkpoint import verify_checkpoint
    from portal_restore_evidence import _canonical, _unique_json

MAX_CHAIN_BYTES = 1024 * 1024
MAX_ENTRIES = 16
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")


def _stamp(value):
    if type(value) is not str:
        raise ValueError("chain checkpoint time missing")
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("malformed chain checkpoint time") from None
    if when.tzinfo is None:
        raise ValueError("chain checkpoint time is timezone-free")
    return when.astimezone(timezone.utc)


def verify_chain(chain, anchor, roles, observer, now=None):
    now = now or datetime.now(timezone.utc)
    if (not isinstance(anchor, dict) or set(anchor) != {
        "version", "scope", "start_sequence", "start_sha256", "end_sequence",
        "end_sha256", "release_sha", "topology_sha256"
    } or type(anchor["version"]) is not int or anchor["version"] != 1 or
        anchor["scope"] != "operator_pinned_synthetic_restore_chain" or
        type(anchor["start_sequence"]) is not int or
        not 1 <= anchor["start_sequence"] <= 2**53 or
        type(anchor["end_sequence"]) is not int or
        not anchor["start_sequence"] < anchor["end_sequence"] <= 2**53 or
        type(anchor["start_sha256"]) is not str or
        not SHA64.fullmatch(anchor["start_sha256"]) or
        type(anchor["end_sha256"]) is not str or
        not SHA64.fullmatch(anchor["end_sha256"]) or
        type(anchor["release_sha"]) is not str or
        not SHA40.fullmatch(anchor["release_sha"]) or
        type(anchor["topology_sha256"]) is not str or
        not SHA64.fullmatch(anchor["topology_sha256"])):
        raise ValueError("independently supplied chain endpoints are not pinned")
    if (not isinstance(chain, dict) or set(chain) != {"version", "scope", "entries"} or
        type(chain["version"]) is not int or chain["version"] != 1 or
        chain["scope"] != "synthetic_restore_checkpoint_chain" or
        not isinstance(chain["entries"], list) or
        not 2 <= len(chain["entries"]) <= MAX_ENTRIES or
        anchor["end_sequence"] - anchor["start_sequence"] != len(chain["entries"])):
        raise ValueError("chain length or envelope differs from external endpoints")
    prior = anchor["start_sha256"]
    seen_nonces = set()
    previous_checkpoint_time = None
    previous_receipt_time = None
    pinned_images = None
    for index, entry in enumerate(chain["entries"], 1):
        if not isinstance(entry, dict) or set(entry) != {"receipt", "checkpoint"}:
            raise ValueError("unexpected chain entry fields")
        receipt, checkpoint = entry["receipt"], entry["checkpoint"]
        expected_sequence = anchor["start_sequence"] + index
        verified = verify_checkpoint(
            checkpoint, observer, receipt, roles,
            expected_sequence, prior, anchor["release_sha"],
            anchor["topology_sha256"], now=now,
        )
        nonce = receipt["fixture_nonce"]
        if nonce in seen_nonces:
            raise ValueError("synthetic fixture nonce replayed within checkpoint chain")
        seen_nonces.add(nonce)
        checkpoint_time = _stamp(checkpoint["payload"]["observed_at"])
        receipt_time = _stamp(receipt["observed_at"])
        if (previous_checkpoint_time is not None and
            checkpoint_time <= previous_checkpoint_time) or (
                previous_receipt_time is not None and
                receipt_time <= previous_receipt_time):
            raise ValueError("nonmonotonic signed restore observation time")
        previous_checkpoint_time, previous_receipt_time = checkpoint_time, receipt_time
        images = _canonical(sorted(receipt["images"], key=lambda item: item["service"]))
        if pinned_images is not None and images != pinned_images:
            raise ValueError("stateful image identities changed within pinned chain")
        pinned_images = images
        prior = verified["checkpoint_sha256"]
    if prior != anchor["end_sha256"]:
        raise ValueError("last checkpoint does not match independently pinned end hash")
    return {
        "source": "synthetic_restore_checkpoint_chain",
        "start_sequence": anchor["start_sequence"],
        "end_sequence": anchor["end_sequence"],
        "verified_checkpoint_count": len(chain["entries"]),
        "chain_sha256": prior,
        "start_and_end_hashes_match_external_values": True,
        "checkpoint_links_and_signatures_valid": True,
        "distinct_fixture_nonces": True,
        "image_identities_unchanged": True,
        "independent_external_anchor_custody_verified": False,
        "durable_external_high_water_verified": False,
        "restore_operations_independently_observed": False,
        "production_recovery_approved": False,
    }


def _private_input(path, limit):
    # The chain can contain multiple signed receipts, unlike the individual
    # 64 KiB public-key trust files. Open no-follow then check the opened inode
    # before reading, rather than trusting an attacker-controlled path stat.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or
                st.st_mode & 0o077 or not 0 < st.st_size <= limit):
            raise ValueError("private operator-controlled chain input required")
        with os.fdopen(fd, "rb") as src:
            fd = -1
            raw = src.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("private checkpoint input exceeds length cap")
        return _unique_json(raw.decode("utf-8", "strict"))
    finally:
        if fd != -1:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chain", required=True)
    parser.add_argument("--external-anchor", required=True)
    parser.add_argument("--external-role-trust", required=True)
    parser.add_argument("--external-observer-trust", required=True)
    args = parser.parse_args()
    try:
        sources = [Path(x) for x in (args.chain, args.external_anchor,
                    args.external_role_trust, args.external_observer_trust)]
        if len({(file.stat().st_dev, file.stat().st_ino) for file in sources}) != 4:
            raise ValueError("anchor, keys and chain must be distinct private files")
        result = verify_chain(
            _private_input(args.chain, MAX_CHAIN_BYTES),
            _private_input(args.external_anchor, 65536),
            _private_input(args.external_role_trust, 65536),
            _private_input(args.external_observer_trust, 65536),
        )
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, subprocess.SubprocessError) as exc:
        raise SystemExit("RELEASE HOLD: synthetic checkpoint chain invalid: " + str(exc)) from None
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
