#!/usr/bin/env python3
"""Offline, role-signed SYNTHETIC Postgres/MinIO restore receipt verification.

No Docker access, SSH, credentials, database queries, image downloads or
writes to fleet systems. Signatures authenticate statements; they cannot
prove custody independence or that a claimed operation actually occurred.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
SIG = re.compile(r"[a-f0-9]{128}\Z")
FINGERPRINT = re.compile(r"[a-f0-9]{64}\Z")
ROLE = ("executor", "independent_reviewer")
IMAGES = ("spatial-postgres", "spatial-minio")
REPOSITORIES = {"spatial-postgres": "postgis/postgis",
                "spatial-minio": "minio/minio"}
VOLUMES = {"spatial-postgres": "spatial_postgres_data",
           "spatial-minio": "spatial_minio_data"}
MAX_BYTES = 65536
MAX_AGE = timedelta(hours=24)


def _sha(value):
    return type(value) is str and bool(SHA64.fullmatch(value))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _utc(value, now):
    if type(value) is not str:
        raise ValueError("missing receipt time")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid receipt time") from None
    if stamp.tzinfo is None or not now - MAX_AGE <= stamp.astimezone(timezone.utc) <= now + timedelta(minutes=5):
        raise ValueError("restore evidence is stale, future dated or timezone-free")


def _read_private_json(path, *, limit=MAX_BYTES):
    """Read only an already-open, private regular inode, never a path after stat.

    The identity and permissions examined here belong to the same descriptor
    that is read. No path.stat()/read_text() gap or symlink-following fallback.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        entry = os.fstat(fd)
        if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.getuid() or
                entry.st_mode & 0o077 or not 0 < entry.st_size <= limit):
            raise ValueError("private, owner-controlled regular restore input required")
        with os.fdopen(fd, "rb") as content:
            fd = -1
            raw = content.read(limit + 1)
        if not 0 < len(raw) <= limit:
            raise ValueError("private restore input length cap exceeded")
        return _unique_json(raw.decode("utf-8", "strict"))
    finally:
        if fd != -1:
            os.close(fd)


def _validate_claim(claim, now):
    required = {"version", "scope", "environment", "project", "release_sha",
                "topology_sha256", "fixture_nonce", "observed_at", "images",
                "database", "objects", "negative_tests", "signatures"}
    if not isinstance(claim, dict) or set(claim) != required:
        raise ValueError("unexpected restore-evidence schema")
    if type(claim["version"]) is not int or claim["version"] != 1 or claim["scope"] != "synthetic_isolated_restore":
        raise ValueError("not an isolated synthetic restore claim")
    if claim["environment"] != "staging" or claim["project"] != "kipnerter-staging":
        raise ValueError("restore evidence is not from isolated staging")
    if not isinstance(claim["release_sha"], str) or not SHA40.fullmatch(claim["release_sha"]):
        raise ValueError("release must have exact immutable SHA")
    if not _sha(claim["topology_sha256"]):
        raise ValueError("missing preflight topology identity")
    nonce = claim["fixture_nonce"]
    if (type(nonce) is not str or not re.fullmatch(r"[a-f0-9]{32}", nonce)):
        raise ValueError("fixture must have a unique 128-bit nonce")
    _utc(claim["observed_at"], now)
    if not isinstance(claim["images"], list) or len(claim["images"]) != 2:
        raise ValueError("expected exactly two image claims")
    services = set()
    for item in claim["images"]:
        if not isinstance(item, dict) or set(item) != {"service", "reference", "volume"}:
            raise ValueError("unexpected image claim keys")
        name = item["service"]
        if name not in IMAGES or name in services:
            raise ValueError("duplicated or unknown stateful service")
        services.add(name)
        ref = item["reference"]
        if (type(ref) is not str or not re.fullmatch(
            re.escape(REPOSITORIES[name]) + r"(?:\:[a-zA-Z0-9_.-]+)?@sha256:[a-f0-9]{64}", ref)
                or item["volume"] != "kipnerter-staging_" + VOLUMES[name]):
            raise ValueError("image digest or isolated named volume unqualified")
    if services != set(IMAGES):
        raise ValueError("missing stateful image")

    database = claim["database"]
    if not isinstance(database, dict) or set(database) != {
        "backup_sha256", "backup_bytes", "source_rows", "restored_rows",
        "source_schema_sha256", "restored_schema_sha256",
        "source_logical_sha256", "restored_logical_sha256"
    }:
        raise ValueError("malformed database receipt")
    for field in ("backup_sha256", "source_schema_sha256", "restored_schema_sha256",
                  "source_logical_sha256", "restored_logical_sha256"):
        if not _sha(database[field]):
            raise ValueError("invalid database digest")
    if (type(database["backup_bytes"]) is not int or
            not 0 < database["backup_bytes"] <= 20 * 1024**3 or
            type(database["source_rows"]) is not int or
            not 1 <= database["source_rows"] <= 10000000 or
            type(database["restored_rows"]) is not int or
            database["restored_rows"] != database["source_rows"] or
            database["source_schema_sha256"] != database["restored_schema_sha256"] or
            database["source_logical_sha256"] != database["restored_logical_sha256"]):
        raise ValueError("database logical restoration mismatch")

    objects = claim["objects"]
    if not isinstance(objects, dict) or set(objects) != {
        "backup_sha256", "backup_bytes", "source_count", "restored_count",
        "source_inventory_sha256", "restored_inventory_sha256"
    }:
        raise ValueError("malformed object restore receipt")
    for field in ("backup_sha256", "source_inventory_sha256", "restored_inventory_sha256"):
        if not _sha(objects[field]):
            raise ValueError("invalid object receipt digest")
    if (type(objects["backup_bytes"]) is not int or
            not 0 < objects["backup_bytes"] <= 20 * 1024**3 or
            type(objects["source_count"]) is not int or
            not 1 <= objects["source_count"] <= 10000000 or
            type(objects["restored_count"]) is not int or
            objects["restored_count"] != objects["source_count"] or
            objects["source_inventory_sha256"] != objects["restored_inventory_sha256"]):
        raise ValueError("object inventory restoration mismatch")
    negative = claim["negative_tests"]
    if not isinstance(negative, dict) or set(negative) != {
        "truncated_db_backup_rejected", "tampered_object_rejected",
        "restore_destination_is_new", "writers_quiesced"
    } or any(negative[x] is not True for x in negative):
        raise ValueError("required negative restore controls not witnessed")
    return {x: claim[x] for x in required if x != "signatures"}


def _verify_sig(public, payload, signature):
    # Binary-compatible OpenSSL Ed25519, without a Python crypto dependency.
    # Private keys are NEVER read by this verifier.
    with tempfile.TemporaryDirectory(prefix="restore-verification-") as d:
        root = Path(d)
        pub, msg, sig = root/"pub.pem", root/"payload", root/"signature"
        pub.write_text(public)
        msg.write_bytes(payload)
        sig.write_bytes(bytes.fromhex(signature))
        proc = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin",
                               "-inkey", str(pub), "-rawin", "-in", str(msg),
                               "-sigfile", str(sig)],
                              timeout=5, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False)
        return proc.returncode == 0


def verify(evidence, trust, now=None, expected_release=None, expected_topology=None):
    now = now or datetime.now(timezone.utc)
    payload_claim = _validate_claim(evidence, now)
    if expected_release is not None and (
            not isinstance(expected_release, str) or
            not SHA40.fullmatch(expected_release) or
            evidence["release_sha"] != expected_release):
        raise ValueError("signed receipt does not match requested exact release")
    if expected_topology is not None and (
            not _sha(expected_topology) or
            evidence["topology_sha256"] != expected_topology):
        raise ValueError("signed receipt does not match trusted preflight topology")
    if (not isinstance(trust, dict) or set(trust) != {"version", "scope", "roles"} or
            trust["version"] != 1 or trust["scope"] != "staging_synthetic_restore" or
            not isinstance(trust["roles"], dict) or set(trust["roles"]) != set(ROLE)):
        raise ValueError("external, role-pinned trust root required")
    signed_roles = evidence["signatures"]
    if not isinstance(signed_roles, dict) or set(signed_roles) != set(ROLE):
        raise ValueError("both independent role signatures required")
    distinct_keys = set()
    bytes_to_verify = _canonical(payload_claim)
    for role in ROLE:
        key = trust["roles"][role]
        record = signed_roles[role]
        if (not isinstance(key, dict) or set(key) != {"key_id", "public_key_pem"} or
                not isinstance(record, dict) or set(record) != {"key_id", "signature"}):
            raise ValueError("invalid independent role identity")
        key_id, public, signature = key["key_id"], key["public_key_pem"], record["signature"]
        if (type(key_id) is not str or not FINGERPRINT.fullmatch(key_id) or
                type(public) is not str or not public.startswith("-----BEGIN PUBLIC KEY-----") or
                len(public) > 512 or key_id in distinct_keys or
                record["key_id"] != key_id or type(signature) is not str or
                not SIG.fullmatch(signature)):
            raise ValueError("untrusted signing role")
        distinct_keys.add(key_id)
        # SPKI fingerprint is fixed by the separately controlled trust file.
        with tempfile.TemporaryDirectory(prefix="restore-key-check-") as d:
            file = Path(d)/"public.pem"
            file.write_text(public)
            result = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(file),
                                     "-outform", "DER"], timeout=5,
                                    capture_output=True, check=False)
            if result.returncode != 0 or hashlib.sha256(result.stdout).hexdigest() != key_id:
                raise ValueError("trust-root public key fingerprint mismatch")
        if not _verify_sig(public, bytes_to_verify, signature):
            raise ValueError("independent role signature invalid")
    return {"source": "signed_synthetic_restore_claim",
            "release_sha": evidence["release_sha"],
            "topology_sha256": evidence["topology_sha256"],
            "signed_claim_sha256": hashlib.sha256(bytes_to_verify).hexdigest(),
            "cryptographic_role_signatures_valid": True,
            "distinct_public_keys": True,
            "restore_operations_independently_observed": False,
            "administrative_key_custody_verified": False,
            "rollback_replay_protection_verified": False,
            "production_recovery_approved": False}


def _unique_json(text):
    def pairs(values):
        obj = {}
        for key, value in values:
            if key in obj:
                raise ValueError("duplicate receipt/trust JSON field")
            obj[key] = value
        return obj
    return json.loads(text, object_pairs_hook=pairs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--external-trust-root", required=True)
    parser.add_argument("--expected-release-sha", required=True)
    parser.add_argument("--expected-topology-sha256", required=True)
    args = parser.parse_args()
    try:
        output = verify(_read_private_json(args.evidence),
                        _read_private_json(args.external_trust_root),
                        expected_release=args.expected_release_sha,
                        expected_topology=args.expected_topology_sha256)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, subprocess.SubprocessError) as exc:
        raise SystemExit("RELEASE HOLD: synthetic restore claim not verified: " + str(exc)) from None
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
