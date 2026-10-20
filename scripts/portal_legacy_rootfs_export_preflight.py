#!/usr/bin/env python3
"""Read-only feasibility check for preserving old live container rootfs.

No docker export/commit/save, images, layer access, paths, env, volumes or
production mutation. A rootfs export is NOT equivalent to an old OCI image.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path("/opt/kipnerter")
ROLES = {
    "kipnerter-api-1": ("kipnerter-api", "sha256:7efc68e54ff1289ee2033440ea0ee176962e3a57e0d24e091a2365ca769d5860"),
    "kipnerter-web-1": ("kipnerter-web", "sha256:5dfd3de1d45260b826d52eb107df8398e872121c9d98ade02540f3917fc78726"),
}
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
MIN_FREE = 20 * 1024**3
MAX_ROOTFS = 2 * 1024**3
MAX_RW = 512 * 1024**2
MAX_OUTPUT = 4096


def run(args: list[str], timeout: int = 10) -> str:
    result = subprocess.run(args, capture_output=True, text=True,
                            timeout=timeout, check=True)
    if len(result.stdout) > MAX_OUTPUT:
        raise ValueError("unbounded Docker metadata")
    return result.stdout.strip()


def validate(rows: dict, cached: dict, free: int) -> dict:
    if not isinstance(rows, dict) or set(rows) != set(ROLES):
        raise ValueError("unexpected container set")
    if not isinstance(cached, dict) or set(cached) != set(ROLES):
        raise ValueError("unexpected image-cache results")
    if type(free) is not int or free < MIN_FREE:
        raise ValueError("insufficient local retention capacity")
    root_total = 0
    write_total = 0
    evidence = []
    for role, (expected_ref, expected_image) in ROLES.items():
        row = rows[role]
        if (not isinstance(row, dict) or row.get("running") is not True or
            row.get("project") != "kipnerter" or
            row.get("source_ref") != expected_ref or
            row.get("image") != expected_image or
            row.get("mount_count") != 0):
            raise ValueError("changed running container or mounted state")
        root = row.get("rootfs_bytes")
        writable = row.get("writable_bytes")
        if (type(root) is not int or not 0 < root <= MAX_ROOTFS or
            type(writable) is not int or not 0 <= writable <= MAX_RW):
            raise ValueError("unexpected filesystem size")
        status = cached[role]
        if (not isinstance(status, dict) or
            status.get("old_image_cached") is not False or
            status.get("current_tag_present") is not True or
            status.get("current_tag_image") == expected_image or
            not isinstance(status.get("current_tag_image"), str) or
            not IMAGE.fullmatch(status["current_tag_image"])):
            raise ValueError("unqualified image recovery method")
        evidence.append((role, expected_ref, expected_image))
        root_total += root
        write_total += writable
    if root_total * 2 + MIN_FREE > free:
        raise ValueError("local rootfs retention lacks conservative headroom")
    fingerprint = hashlib.sha256(json.dumps(evidence,
        separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    return {
        "status": "ROOTFS_EXPORT_FEASIBLE_ONLY",
        "legacy_roles_verified": len(ROLES),
        "live_image_identity_fingerprint_sha256": fingerprint,
        "rootfs_total_mib_upper_bound": (root_total + 1024**2 - 1) // 1024**2,
        "writable_total_mib_upper_bound": (write_total + 1024**2 - 1) // 1024**2,
        "free_gib_floor": free // 1024**3,
        "old_original_images_cached": False,
        "different_images_now_under_legacy_tags": True,
        "container_mounts_present": False,
        "candidate_rootfs_export_created": False,
        "source_archive_already_independently_verified": False,
        "rootfs_export_equivalent_to_old_oci_image": False,
        "recovered_container_launch_metadata": False,
        "isolated_rollback_test_passed": False,
        "production_modified": False,
        "safe_to_cutover": False,
    }


def probe() -> dict:
    rows = {}
    cached = {}
    # All Docker reads request allowlisted scalar fields only: never use
    # full inspection JSON, mounts, environment, or image history.
    fmt = ('{{.State.Running}}|{{.Image}}|{{.Config.Image}}|'
           '{{index .Config.Labels "com.docker.compose.project"}}|'
           '{{len .Mounts}}|{{.SizeRw}}|{{.SizeRootFs}}')
    for role, (ref, old_sha) in ROLES.items():
        line = run(["docker", "inspect", "--size", "--format", fmt, role])
        fields = line.split("|")
        if len(fields) != 7 or not fields[4].isdigit() or not fields[5].isdigit() or not fields[6].isdigit():
            raise ValueError("invalid scalar Docker response")
        rows[role] = {
            "running": fields[0] == "true",
            "image": fields[1],
            "source_ref": fields[2],
            "project": fields[3],
            "mount_count": int(fields[4]),
            "writable_bytes": int(fields[5]),
            "rootfs_bytes": int(fields[6]),
        }
        try:
            run(["docker", "image", "inspect", "--format", "{{.Id}}", old_sha])
            original_cached = True
        except subprocess.CalledProcessError:
            original_cached = False
        try:
            current_tag = run(["docker", "image", "inspect",
                               "--format", "{{.Id}}", ref])
            tag_present = True
        except subprocess.CalledProcessError:
            current_tag = ""
            tag_present = False
        cached[role] = {
            "old_image_cached": original_cached,
            "current_tag_present": tag_present,
            "current_tag_image": current_tag,
        }
    return validate(rows, cached, shutil.disk_usage(ROOT).free)


def main() -> int:
    try:
        result = probe()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "HOLD", "failure_class": type(exc).__name__,
                          "export_created": False, "production_modified": False,
                          "safe_to_cutover": False}, sort_keys=True))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
