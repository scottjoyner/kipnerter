#!/usr/bin/env python3
"""Read-only, four-key check of synthetic checkpoint chain against custodian tip.

This does not write a high-water mark or prove external custody/durability.
A caller-supplied rollback of BOTH the signed tip and chain remains possible.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import subprocess

if __package__:
    from .portal_restore_chain import verify_chain, _private_input, _stamp, SHA40, SHA64
    from .portal_restore_checkpoint import _fingerprint
    from .portal_restore_evidence import _canonical, _verify_sig
else:
    from portal_restore_chain import verify_chain, _private_input, _stamp, SHA40, SHA64
    from portal_restore_checkpoint import _fingerprint
    from portal_restore_evidence import _canonical, _verify_sig

SIG = re.compile(r"[a-f0-9]{128}\Z")
MAX_SEQUENCE = 2**53


def verify_high_water(chain, anchor, roles, observer, signed_tip, custodian_trust, now=None):
    now = now or datetime.now(timezone.utc)
    result = verify_chain(chain, anchor, roles, observer, now=now)
    if not isinstance(signed_tip, dict) or set(signed_tip) != {
            "payload", "custodian_signature"}:
        raise ValueError("invalid high-water signed envelope")
    payload, signature = signed_tip["payload"], signed_tip["custodian_signature"]
    if not isinstance(payload, dict) or set(payload) != {
        "version", "scope", "end_sequence", "end_sha256", "release_sha",
        "topology_sha256", "recorded_at"
    }:
        raise ValueError("unrecognized high-water fields")
    if (type(payload["version"]) is not int or payload["version"] != 1 or
        payload["scope"] != "synthetic_restore_custodian_high_water" or
        type(payload["end_sequence"]) is not int or
        not 2 <= payload["end_sequence"] <= MAX_SEQUENCE or
        type(payload["end_sha256"]) is not str or
        not SHA64.fullmatch(payload["end_sha256"]) or
        type(payload["release_sha"]) is not str or
        not SHA40.fullmatch(payload["release_sha"]) or
        type(payload["topology_sha256"]) is not str or
        not SHA64.fullmatch(payload["topology_sha256"])):
        raise ValueError("invalid high-water field type or value")
    if (payload["release_sha"] != anchor["release_sha"] or
        payload["topology_sha256"] != anchor["topology_sha256"]):
        raise ValueError("custodian high-water release or topology mismatch")
    if payload["end_sequence"] != anchor["end_sequence"]:
        raise ValueError("rollback or unanchored advancement relative to high-water sequence")
    if payload["end_sha256"] != anchor["end_sha256"]:
        raise ValueError("forked high-water checkpoint hash")
    final_stamp = _stamp(chain["entries"][-1]["checkpoint"]["payload"]["observed_at"])
    stamp = _stamp(payload["recorded_at"])
    if stamp < final_stamp or stamp > now + timedelta(minutes=5):
        raise ValueError("high-water publication timestamp inconsistent")
    if (not isinstance(custodian_trust, dict) or set(custodian_trust) != {
        "version", "scope", "custodian"} or
        type(custodian_trust["version"]) is not int or
        custodian_trust["version"] != 1 or
        custodian_trust["scope"] != "synthetic_restore_custodian_trust" or
        not isinstance(custodian_trust["custodian"], dict) or
        set(custodian_trust["custodian"]) != {"key_id", "public_key_pem"}):
        raise ValueError("custodian trust root required")
    if (not isinstance(signature, dict) or set(signature) != {"key_id", "signature"} or
        type(signature["signature"]) is not str or
        not SIG.fullmatch(signature["signature"])):
        raise ValueError("invalid custodian signature")
    signer = custodian_trust["custodian"]
    if (type(signer["key_id"]) is not str or
        signer["key_id"] != signature["key_id"] or
        signer["key_id"] in {
            roles["roles"]["executor"]["key_id"],
            roles["roles"]["independent_reviewer"]["key_id"],
            observer["observer"]["key_id"]
        }):
        raise ValueError("custodian must have a distinct fourth signing key")
    _fingerprint(signer["public_key_pem"], signer["key_id"])
    if not _verify_sig(signer["public_key_pem"], _canonical(payload), signature["signature"]):
        raise ValueError("custodian high-water signature invalid")
    return {
        "source": "read_only_signed_synthetic_high_water_tip",
        "verified_checkpoint_count": result["verified_checkpoint_count"],
        "end_sequence": payload["end_sequence"],
        "end_sha256": payload["end_sha256"],
        "signed_tip_sha256": hashlib.sha256(_canonical(signed_tip)).hexdigest(),
        "four_distinct_public_keys": True,
        "custodian_signature_valid": True,
        "chain_tip_matches_custodian_record": True,
        "independent_custodian_control_verified": False,
        "rollback_resistant_persistence_verified": False,
        "durable_external_high_water_verified": False,
        "real_restore_verified": False,
        "production_recovery_approved": False,
    }


def main():
    parser = argparse.ArgumentParser()
    for flag in ("chain", "external-anchor", "external-role-trust",
                 "external-observer-trust", "signed-high-water", "external-custodian-trust"):
        parser.add_argument("--" + flag, required=True)
    options = parser.parse_args()
    names = ("chain", "external_anchor", "external_role_trust",
             "external_observer_trust", "signed_high_water", "external_custodian_trust")
    limits = (1024*1024, 65536, 65536, 65536, 65536, 65536)
    try:
        opened = [_private_input(getattr(options, name), limit)
                  for name, limit in zip(names, limits)]
        if len({inode for _, inode in opened}) != len(opened):
            raise ValueError("chain, anchor, records and trust must have distinct opened inodes")
        outcome = verify_high_water(*(value for value, _ in opened))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            subprocess.SubprocessError) as exc:
        raise SystemExit("RELEASE HOLD: high-water receipt not verified: " + str(exc)) from None
    print(json.dumps(outcome, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
