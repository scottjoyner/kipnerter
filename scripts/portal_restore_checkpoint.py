#!/usr/bin/env python3
"""Offline third-role signed checkpoint for a synthetic restore RECEIPT only.

This verifies an operator-pinned checkpoint extension, not independent
administrative custody, durable replay protection, or a real restore.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if __package__:
    from .portal_restore_evidence import (
        _canonical, _stat_trust, _unique_json, _utc, _verify_sig, verify,
    )
else:
    from portal_restore_evidence import (
        _canonical, _stat_trust, _unique_json, _utc, _verify_sig, verify,
    )

DIGEST = re.compile(r"[a-f0-9]{64}\Z")
SIGNATURE = re.compile(r"[a-f0-9]{128}\Z")
MAX_FILE = 65536


def _fingerprint(public, expected):
    if (type(public) is not str or len(public) > 512 or
            not public.startswith("-----BEGIN PUBLIC KEY-----") or
            type(expected) is not str or not DIGEST.fullmatch(expected)):
        raise ValueError("untrusted checkpoint observer public key")
    with tempfile.TemporaryDirectory(prefix="restore-observer-public-") as d:
        path = Path(d) / "public.pem"
        path.write_text(public)
        result = subprocess.run(
            ["openssl", "pkey", "-pubin", "-in", str(path), "-outform", "DER"],
            timeout=5, capture_output=True, check=False,
        )
    if result.returncode or hashlib.sha256(result.stdout).hexdigest() != expected:
        raise ValueError("checkpoint observer public-key fingerprint mismatch")


def verify_checkpoint(checkpoint, checkpoint_trust, signed_receipt, role_trust,
                      expected_sequence, expected_previous_sha256,
                      expected_release, expected_topology, now=None):
    now = now or datetime.now(timezone.utc)
    if (type(expected_sequence) is not int or not 2 <= expected_sequence <= 2**53 or
            type(expected_previous_sha256) is not str or
            not DIGEST.fullmatch(expected_previous_sha256)):
        raise ValueError("external sequence and previous checkpoint SHA must be pinned")
    receipt = verify(signed_receipt, role_trust, now=now,
                     expected_release=expected_release,
                     expected_topology=expected_topology)
    if (not isinstance(checkpoint, dict) or
            set(checkpoint) != {"payload", "observer_signature"}):
        raise ValueError("invalid checkpoint envelope")
    data, signature = checkpoint["payload"], checkpoint["observer_signature"]
    required = {"version", "scope", "receipt_sha256", "fixture_nonce",
                "release_sha", "topology_sha256", "sequence",
                "previous_checkpoint_sha256", "observed_at"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("unexpected observer checkpoint fields")
    if (type(data["version"]) is not int or data["version"] != 1 or
            data["scope"] != "staging_synthetic_restore_checkpoint" or
            data["receipt_sha256"] != receipt["signed_claim_sha256"] or
            data["fixture_nonce"] != signed_receipt["fixture_nonce"] or
            data["release_sha"] != receipt["release_sha"] or
            data["topology_sha256"] != receipt["topology_sha256"] or
            type(data["sequence"]) is not int or data["sequence"] != expected_sequence or
            data["previous_checkpoint_sha256"] != expected_previous_sha256):
        raise ValueError("checkpoint identity, nonce or external prior anchor mismatch")
    _utc(data["observed_at"], now)
    if datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00")) < datetime.fromisoformat(
            signed_receipt["observed_at"].replace("Z", "+00:00")):
        raise ValueError("checkpoint was signed before restore receipt observation")
    if (not isinstance(checkpoint_trust, dict) or
            set(checkpoint_trust) != {"version", "scope", "observer"} or
            checkpoint_trust["version"] != 1 or
            checkpoint_trust["scope"] != "staging_synthetic_restore_observer" or
            not isinstance(checkpoint_trust["observer"], dict) or
            set(checkpoint_trust["observer"]) != {"key_id", "public_key_pem"}):
        raise ValueError("external observer trust root required")
    if (not isinstance(signature, dict) or
            set(signature) != {"key_id", "signature"} or
            type(signature["signature"]) is not str or
            not SIGNATURE.fullmatch(signature["signature"])):
        raise ValueError("invalid observer signature")
    observer = checkpoint_trust["observer"]
    key_id, key = observer["key_id"], observer["public_key_pem"]
    if (signature["key_id"] != key_id or
            key_id in {role_trust["roles"][r]["key_id"] for r in
                       ("executor", "independent_reviewer")}):
        raise ValueError("observer key must be distinct from receipt signing roles")
    _fingerprint(key, key_id)
    canonical = _canonical(data)
    if not _verify_sig(key, canonical, signature["signature"]):
        raise ValueError("invalid independently keyed observer signature")
    return {
        "source": "signed_synthetic_restore_checkpoint",
        "checkpoint_sha256": hashlib.sha256(_canonical(checkpoint)).hexdigest(),
        "signed_receipt_sha256": receipt["signed_claim_sha256"],
        "checkpoint_sequence": expected_sequence,
        "external_anchor_matches": True,
        "observer_signature_valid": True,
        "third_distinct_public_key": True,
        "restore_operations_independently_observed": False,
        "observer_administrative_custody_verified": False,
        "durable_external_high_water_verified": False,
        "production_recovery_approved": False,
    }


def _read_private_json(path):
    return _unique_json(_stat_trust(path).read_text())


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--receipt", required=True)
    cli.add_argument("--external-role-trust", required=True)
    cli.add_argument("--checkpoint", required=True)
    cli.add_argument("--external-observer-trust", required=True)
    cli.add_argument("--expected-sequence", type=int, required=True)
    cli.add_argument("--expected-prior-sha256", required=True)
    cli.add_argument("--expected-release-sha", required=True)
    cli.add_argument("--expected-topology-sha256", required=True)
    args = cli.parse_args()
    try:
        receipt, roles = _read_private_json(args.receipt), _read_private_json(args.external_role_trust)
        checkpoint = _read_private_json(args.checkpoint)
        witness = _read_private_json(args.external_observer_trust)
        result = verify_checkpoint(checkpoint, witness, receipt, roles,
                                   args.expected_sequence, args.expected_prior_sha256,
                                   args.expected_release_sha, args.expected_topology_sha256)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise SystemExit("RELEASE HOLD: checkpoint witness not verified: " + str(exc)) from None
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
