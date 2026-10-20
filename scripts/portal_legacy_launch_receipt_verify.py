#!/usr/bin/env python3
"""Read-only verifier for private redacted legacy launch custody.

No raw secret, command, env value or hash is printed. No production writes.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

BASE = Path.home() / ".local/state/kipnerter-release/state-backups"
PREFIX = "legacy-launch-metadata-before-17-20261020.json"
ROOTFS = "legacy-rootfs-before-17-20261019"
ROLES = {
    "kipnerter-api-1": "sha256:7efc68e54ff1289ee2033440ea0ee176962e3a57e0d24e091a2365ca769d5860",
    "kipnerter-web-1": "sha256:5dfd3de1d45260b826d52eb107df8398e872121c9d98ade02540f3917fc78726",
}
CONFIG_FIELDS = {"Entrypoint", "Cmd", "WorkingDir", "User", "ExposedPorts",
                 "Healthcheck", "StopSignal"}
HOST_FIELDS = {"NetworkMode", "PortBindings", "RestartPolicy", "ReadonlyRootfs",
               "Init", "CapDrop", "SecurityOpt"}
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")

def unique_pairs(pairs):
    result = {}
    for key, val in pairs:
        if key in result:
            raise ValueError("duplicate private JSON member")
        result[key] = val
    return result

def private_dir(base):
    if (base.is_symlink() or not base.is_dir() or
        base.stat().st_uid != os.getuid() or
        stat.S_IMODE(base.stat().st_mode) != 0o700):
        raise ValueError("owner-private custody directory required")

def private_data(path, maxsize):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        sb = os.fstat(fd)
        if (not stat.S_ISREG(sb.st_mode) or sb.st_uid != os.getuid() or
            stat.S_IMODE(sb.st_mode) != 0o600 or
            not 0 < sb.st_size <= maxsize):
            raise ValueError("unsafe private evidence file")
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read(maxsize + 1)
    finally:
        os.close(fd)

def check_tar(path, size, sha):
    if (type(size) is not int or not 0 < size <= 2 * 1024**3 or
        not isinstance(sha, str) or not DIGEST.fullmatch(sha)):
        raise ValueError("invalid rootfs receipt")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        sb = os.fstat(fd)
        if (not stat.S_ISREG(sb.st_mode) or sb.st_uid != os.getuid() or
            stat.S_IMODE(sb.st_mode) != 0o600 or sb.st_size != size):
            raise ValueError("private rootfs file mismatch")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as f:
            while data := f.read(1024 * 1024):
                digest.update(data)
        if digest.hexdigest() != sha:
            raise ValueError("rootfs archive changed")
    finally:
        os.close(fd)

def valid_shapes(shapes, expected):
    if not isinstance(shapes, dict) or set(shapes) != expected:
        raise ValueError("launch shape fields unexpected")
    for shape in shapes.values():
        if not isinstance(shape, dict):
            raise ValueError("invalid shape")
        if shape == {"present": False}:
            continue
        if (set(shape) != {"present", "kind", "items", "sha256"} or
            shape["present"] is not True or
            shape["kind"] not in ("str", "list", "dict", "bool", "int") or
            type(shape["items"]) is not int or
            not 0 <= shape["items"] <= 512 or
            not isinstance(shape["sha256"], str) or
            not DIGEST.fullmatch(shape["sha256"])):
            raise ValueError("untrusted launch fingerprint")

def validate(metadata, receipt, root_hash):
    if (not isinstance(metadata, dict) or
        set(metadata) != {
          "schema", "purpose", "rootfs_receipt_sha256", "roles",
          "contains_potential_secret_values", "original_oci_images_recovered",
          "runnable_rollback_verified", "independent_admin_custody_verified",
          "production_containers_modified", "safe_to_cutover"
        } or metadata["schema"] != 1 or
        metadata["purpose"] != "legacy_launch_configuration_private_recovery_evidence" or
        metadata["rootfs_receipt_sha256"] != root_hash or
        any(metadata[k] is not False for k in (
          "contains_potential_secret_values", "original_oci_images_recovered",
          "runnable_rollback_verified", "independent_admin_custody_verified",
          "production_containers_modified", "safe_to_cutover"))):
        raise ValueError("unsafe launch evidence or release claims")
    rows = metadata["roles"]
    if (not isinstance(rows, list) or len(rows) != 2 or
        any(not isinstance(x, dict) for x in rows) or
        {x.get("role") for x in rows} != set(ROLES)):
        raise ValueError("changed launch identity set")
    for row in rows:
        role = row["role"]
        if (set(row) != {
              "role", "image_id", "source_ref", "started_at",
              "environment_names_only", "configuration_fingerprints",
              "host_configuration_fingerprints", "raw_environment_values_retained",
              "raw_command_or_host_values_retained"} or
            row["image_id"] != ROLES[role] or
            row["source_ref"] != ("kipnerter-api" if "api" in role else "kipnerter-web") or
            not isinstance(row["started_at"], str) or not row["started_at"].endswith("Z") or
            row["raw_environment_values_retained"] is not False or
            row["raw_command_or_host_values_retained"] is not False):
            raise ValueError("unsafe launch role")
        keys = row["environment_names_only"]
        if (not isinstance(keys, list) or len(keys) > 512 or
            sorted(set(keys)) != keys or
            any(not isinstance(x, str) or not ENV_NAME.fullmatch(x) for x in keys)):
            raise ValueError("environment variable values or malformed names")
        valid_shapes(row["configuration_fingerprints"], CONFIG_FIELDS)
        valid_shapes(row["host_configuration_fingerprints"], HOST_FIELDS)
    if (not isinstance(receipt, dict) or
        set(receipt) != {
          "schema", "metadata_file_sha256", "metadata_bytes", "role_count",
          "rootfs_receipt_sha256", "contains_potential_secret_values",
          "old_oci_images_recovered", "runnable_rollback_verified",
          "independent_admin_custody_verified", "safe_to_cutover"
        } or receipt["schema"] != 1 or receipt["role_count"] != 2 or
        receipt["rootfs_receipt_sha256"] != root_hash or
        any(receipt[k] is not False for k in (
          "contains_potential_secret_values", "old_oci_images_recovered",
          "runnable_rollback_verified", "independent_admin_custody_verified",
          "safe_to_cutover"))):
        raise ValueError("inconsistent private receipt")
    return rows

def verify(base=BASE, live_check=True):
    private_dir(base)
    raw_root = private_data(base / (ROOTFS + ".receipt.json"), 16384)
    root = json.loads(raw_root, object_pairs_hook=unique_pairs)
    if (not isinstance(root, dict) or root.get("schema") != 1 or
        root.get("rootfs_files_created") is not True or
        root.get("safe_to_cutover") is not False or
        root.get("runnable_rollback_verified") is not False):
        raise ValueError("rootfs provenance invalid")
    parts = root.get("roles")
    if (not isinstance(parts, list) or len(parts) != 2 or
        any(not isinstance(x, dict) for x in parts) or
        {x.get("role") for x in parts} != set(ROLES)):
        raise ValueError("rootfs roles mismatch")
    for item in parts:
        if item.get("source_image") != ROLES[item["role"]]:
            raise ValueError("rootfs original image mismatch")
        check_tar(base / (ROOTFS + "-" + item["role"] + ".tar"),
                  item.get("rootfs_tar_bytes"), item.get("rootfs_tar_sha256"))
    raw = private_data(base / PREFIX, 1024 * 1024)
    receiptraw = private_data(base / (PREFIX + ".receipt.json"), 16384)
    rec = json.loads(receiptraw, object_pairs_hook=unique_pairs)
    metadata = json.loads(raw, object_pairs_hook=unique_pairs)
    if rec.get("metadata_file_sha256") != hashlib.sha256(raw).hexdigest() or (
        rec.get("metadata_bytes") != len(raw)):
        raise ValueError("metadata receipt digest mismatch")
    rows = validate(metadata, rec, hashlib.sha256(raw_root).hexdigest())
    if live_check:
        for row in rows:
            # Scalar fields only: no Docker env, configuration values or mounts.
            out = subprocess.run(
                ["docker", "inspect", "--format",
                 '{{.State.Running}}|{{.Image}}|{{.State.StartedAt}}|{{len .Mounts}}',
                 row["role"]], capture_output=True, text=True, check=True,
                timeout=10)
            if out.stdout.strip().split("|") != [
                "true", row["image_id"], row["started_at"], "0"]:
                raise ValueError("original live container changed")
    return {"status": "PRIVATE_LAUNCH_RECEIPT_VERIFIED",
            "archived_rootfs_count": len(parts),
            "redacted_launch_roles": len(rows), "live_identity_checked": live_check,
            "old_oci_images_recovered": False, "runnable_rollback": False,
            "independent_admin_custody": False,
            "production_modified": False, "safe_to_cutover": False}

def main():
    try:
        print(json.dumps(verify(), sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, IndexError,
            json.JSONDecodeError, subprocess.SubprocessError):
        print(json.dumps({"status": "HOLD", "production_modified": False,
                          "safe_to_cutover": False}, sort_keys=True))
        raise SystemExit(2)

if __name__ == "__main__":
    main()
