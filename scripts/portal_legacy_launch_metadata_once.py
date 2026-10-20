#!/usr/bin/env python3
"""One-shot private capture of old API/web launch settings; never log secrets.

Read-only Docker inspect; writes only create-once owner-private JSON/receipt.
This does not produce a runnable image or authorize any release.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

BACKUPS = Path.home() / ".local/state/kipnerter-release/state-backups"
ROOTFS_RECEIPT = "legacy-rootfs-before-17-20261019.receipt.json"
TARGET = "legacy-launch-metadata-before-17-20261020.json"
RECEIPT = TARGET + ".receipt.json"
ROLES = {
    "kipnerter-api-1": ("kipnerter-api", "sha256:7efc68e54ff1289ee2033440ea0ee176962e3a57e0d24e091a2365ca769d5860"),
    "kipnerter-web-1": ("kipnerter-web", "sha256:5dfd3de1d45260b826d52eb107df8398e872121c9d98ade02540f3917fc78726"),
}
MAX_INSPECT_BYTES = 512 * 1024
MAX_PRIVATE_BYTES = 1024 * 1024

def no_duplicate_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous JSON object")
        result[key] = value
    return result

def owner_file(path: Path, mode: int):
    if (path.is_symlink() or not path.is_file() or
        path.stat().st_uid != os.getuid() or
        stat.S_IMODE(path.stat().st_mode) != mode):
        raise ValueError("private evidence file required")

def custody(base: Path):
    if (base.is_symlink() or not base.is_dir() or
        base.stat().st_uid != os.getuid() or
        stat.S_IMODE(base.stat().st_mode) != 0o700):
        raise ValueError("private 0700 backup directory required")

def verified_rootfs_receipt(base: Path):
    p = base / ROOTFS_RECEIPT
    owner_file(p, 0o600)
    if p.stat().st_size > 16_384:
        raise ValueError("rootfs receipt oversized")
    data = json.loads(p.read_bytes(), object_pairs_hook=no_duplicate_json_pairs)
    if (data.get("schema") != 1 or
        data.get("rootfs_files_created") is not True or
        data.get("safe_to_cutover") is not False or
        data.get("legacy_container_images_recovered") is not False or
        data.get("runnable_rollback_verified") is not False):
        raise ValueError("invalid original rootfs receipt")
    roles = data.get("roles")
    if (not isinstance(roles, list) or len(roles) != 2 or
        {r.get("role") for r in roles if isinstance(r, dict)} != set(ROLES)):
        raise ValueError("rootfs role set mismatch")
    for r in roles:
        role = r["role"]
        if r.get("source_image") != ROLES[role][1]:
            raise ValueError("old image identity mismatch")
        tar = base / ("legacy-rootfs-before-17-20261019-" + role + ".tar")
        owner_file(tar, 0o600)
        if not 0 < tar.stat().st_size <= 2 * 1024**3 or tar.stat().st_size != r.get("rootfs_tar_bytes"):
            raise ValueError("private rootfs archive missing or size mismatch")
        digest = hashlib.sha256()
        with tar.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != r.get("rootfs_tar_sha256"):
            raise ValueError("private rootfs archive checksum mismatch")
    return hashlib.sha256(p.read_bytes()).hexdigest()

def extract_launch_metadata(doc, role):
    if not isinstance(doc, dict) or role not in ROLES:
        raise ValueError("unexpected Docker inspect response")
    ref, old_image = ROLES[role]
    cfg, host, state = doc.get("Config"), doc.get("HostConfig"), doc.get("State")
    labels = (cfg or {}).get("Labels") or {}
    if (doc.get("Name") != "/" + role or
        doc.get("Image") != old_image or not isinstance(cfg, dict) or
        cfg.get("Image") != ref or
        not isinstance(host, dict) or not isinstance(state, dict) or
        state.get("Running") is not True or
        not isinstance(state.get("StartedAt"), str) or
        not state["StartedAt"].endswith("Z") or
        labels.get("com.docker.compose.project") != "kipnerter" or
        doc.get("Mounts") != []):
        raise ValueError("changed legacy container identity")
    # Preserve only structural fingerprints. Commands, health checks, network
    # values and secrets are never persisted or emitted in plaintext.
    def digest_shape(value):
        if value is None:
            return {"present": False}
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        if len(raw) > 256 * 1024:
            raise ValueError("launch field too large")
        return {"present": True, "kind": type(value).__name__,
                "items": len(value) if isinstance(value, (list, dict)) else 1,
                "sha256": hashlib.sha256(raw).hexdigest()}

    env = cfg.get("Env") or []
    if not isinstance(env, list) or len(env) > 512 or any(
        not isinstance(item, str) or "=" not in item for item in env
    ):
        raise ValueError("malformed environment")
    names = sorted({item.split("=", 1)[0] for item in env})
    if any(not name or len(name) > 128 or
           not name.replace("_", "A").isalnum() for name in names):
        raise ValueError("invalid environment key")
    return {
        "role": role,
        "image_id": old_image,
        "source_ref": ref,
        "started_at": state["StartedAt"],
        "environment_names_only": names,
        "configuration_fingerprints": {
            key: digest_shape(cfg.get(key)) for key in
            ("Entrypoint", "Cmd", "WorkingDir", "User", "ExposedPorts",
             "Healthcheck", "StopSignal")
        },
        "host_configuration_fingerprints": {
            key: digest_shape(host.get(key)) for key in
            ("NetworkMode", "PortBindings", "RestartPolicy", "ReadonlyRootfs",
             "Init", "CapDrop", "SecurityOpt")
        },
        "raw_environment_values_retained": False,
        "raw_command_or_host_values_retained": False,
    }

def inspect_one(role):
    try:
        result = subprocess.run(
            ["docker", "inspect", "--type", "container", role],
            check=True, capture_output=True, timeout=15)
        if len(result.stdout) > MAX_INSPECT_BYTES or not result.stdout:
            raise ValueError("unbounded container metadata")
        objs = json.loads(result.stdout, object_pairs_hook=no_duplicate_json_pairs)
        if not isinstance(objs, list) or len(objs) != 1:
            raise ValueError("ambiguous Docker container")
        return extract_launch_metadata(objs[0], role)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("Docker metadata unavailable") from None

def evidence(base=BACKUPS):
    custody(base)
    if (os.path.lexists(base / TARGET) or os.path.lexists(base / RECEIPT) or
        any(base.glob(".launch-metadata-incomplete-*"))):
        raise ValueError("one-shot metadata already exists")
    rootfs_hash = verified_rootfs_receipt(base)
    before = [inspect_one(role) for role in ROLES]
    content = {
        "schema": 1,
        "purpose": "legacy_launch_configuration_private_recovery_evidence",
        "rootfs_receipt_sha256": rootfs_hash,
        "roles": before,
        "contains_potential_secret_values": False,
        "original_oci_images_recovered": False,
        "runnable_rollback_verified": False,
        "independent_admin_custody_verified": False,
        "production_containers_modified": False,
        "safe_to_cutover": False,
    }
    raw = (json.dumps(content, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(raw) > MAX_PRIVATE_BYTES:
        raise ValueError("private metadata too large")
    after = [inspect_one(role) for role in ROLES]
    if before != after:
        raise ValueError("live container changed during read-only inspection")
    fd, tmp = tempfile.mkstemp(prefix=".launch-metadata-incomplete-", dir=base)
    os.fchmod(fd, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, base / TARGET)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)
    receipt = {
        "schema": 1, "metadata_file_sha256": hashlib.sha256(raw).hexdigest(),
        "metadata_bytes": len(raw), "role_count": 2,
        "rootfs_receipt_sha256": rootfs_hash,
        "contains_potential_secret_values": False,
        "old_oci_images_recovered": False,
        "runnable_rollback_verified": False,
        "independent_admin_custody_verified": False,
        "safe_to_cutover": False,
    }
    fd = os.open(base / RECEIPT, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(receipt, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {"status": "PRIVATE_LAUNCH_METADATA_PRESERVED_NOT_OCI_ROLLBACK",
            "role_count": 2, "metadata_receipt_saved": True,
            "contains_potential_secret_values": False,
            "production_containers_modified": False, "safe_to_cutover": False}

def main():
    try:
        print(json.dumps(evidence(), sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        print(json.dumps({"status": "HOLD",
                          "private_partial_may_exist": True,
                          "production_containers_modified": False,
                          "safe_to_cutover": False}, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
