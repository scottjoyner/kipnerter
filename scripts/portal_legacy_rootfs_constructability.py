#!/usr/bin/env python3
"""Read-only constructability audit for the TWO privately retained legacy rootfs exports.

A Docker rootfs export is NOT the original OCI image: no layer chain, metadata,
Entrypoint/Cmd, environment values, provenance or runnable rollback is implied.
No production files are opened unless an authorized operator separately invokes
this audit on their owner-private custody directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile

MAX_ARCHIVE = 2 * 1024**3
MAX_RECEIPT = 16384
MAX_MEMBERS = 200000
MAX_NAME = 4096
PREFIX = "legacy-rootfs-before-17-20261019"
ROLES = {
    "kipnerter-api-1": "sha256:7efc68e54ff1289ee2033440ea0ee176962e3a57e0d24e091a2365ca769d5860",
    "kipnerter-web-1": "sha256:5dfd3de1d45260b826d52eb107df8398e872121c9d98ade02540f3917fc78726",
}
HEX = re.compile(r"[a-f0-9]{64}\Z")
# Report only category counts: raw Docker rootfs paths can expose sensitive names.
SENSITIVE_SEGMENTS = {
    ".env", ".ssh", ".aws", ".kube", ".npmrc", ".pypirc",
    "secrets", "credentials", "private", ".docker",
}


def strict_json(raw: bytes):
    def unique(pairs):
        found = {}
        for key, value in pairs:
            if key in found:
                raise ValueError("duplicate private receipt field")
            found[key] = value
        return found
    return json.loads(raw, object_pairs_hook=unique)


def _private_file(dirfd: int, name: str, *, max_size: int):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                 os.O_CLOEXEC, dir_fd=dirfd)
    try:
        state = os.fstat(fd)
        if (not stat.S_ISREG(state.st_mode) or state.st_uid != os.getuid()
                or stat.S_IMODE(state.st_mode) != 0o600
                or state.st_nlink != 1 or
                not 0 < state.st_size <= max_size):
            raise ValueError("untrusted private legacy archive or receipt")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def _private_dir(base: Path) -> int:
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY |
                 os.O_NOFOLLOW | os.O_CLOEXEC)
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        os.close(fd)
        raise ValueError("private rootfs custody directory required")
    return fd


def _valid_entry_name(name: str):
    if (not isinstance(name, str) or not 0 < len(name) <= MAX_NAME
            or "\\" in name or "\x00" in name or name.startswith("/")):
        raise ValueError("unsafe Docker rootfs path structure")
    segments = [p for p in name.split("/") if p not in ("", ".")]
    if not segments or ".." in segments:
        raise ValueError("unsafe Docker rootfs path structure")
    return segments


def _audit_tar(opened, *, declared_count: int):
    if type(declared_count) is not int or not 1 <= declared_count <= MAX_MEMBERS:
        raise ValueError("invalid declared rootfs member count")
    opened.seek(0)
    seen = set()
    result = {
        "member_count": 0,
        "regular_files": 0,
        "directories": 0,
        "links_needing_review": 0,
        "special_nodes_needing_review": 0,
        "sensitive_name_categories_needing_review": 0,
        "nonzero_setuid_or_setgid_entries": 0,
        "manifest_or_config_recovered": False,
        "rootfs_equivalent_to_original_oci": False,
        "runnable_rollback_verified": False,
    }
    with tarfile.open(fileobj=opened, mode="r:") as handle:
        for entry in handle:
            result["member_count"] += 1
            if result["member_count"] > MAX_MEMBERS or entry.size > MAX_ARCHIVE:
                raise ValueError("oversized legacy export member count or length")
            parts = _valid_entry_name(entry.name)
            normalized = "/".join(parts)
            if normalized in seen:
                raise ValueError("duplicate legacy rootfs path")
            seen.add(normalized)
            if entry.isfile():
                result["regular_files"] += 1
            elif entry.isdir():
                result["directories"] += 1
            elif entry.issym() or entry.islnk():
                result["links_needing_review"] += 1
            elif entry.isfifo() or entry.ischr() or entry.isblk():
                result["special_nodes_needing_review"] += 1
            else:
                raise ValueError("unknown legacy rootfs tar type")
            if set(parts) & SENSITIVE_SEGMENTS:
                result["sensitive_name_categories_needing_review"] += 1
            if entry.mode & 0o6000:
                result["nonzero_setuid_or_setgid_entries"] += 1
    if result["member_count"] != declared_count:
        raise ValueError("rootfs receipt/member-count mismatch")
    return result


def _verify_tar(dirfd, *, role: str, size: int, expected_sha: str,
                count: int):
    if (type(size) is not int or not 0 < size <= MAX_ARCHIVE or
            type(expected_sha) is not str or not HEX.fullmatch(expected_sha)):
        raise ValueError("invalid private rootfs receipt hash or length")
    with _private_file(dirfd, PREFIX + "-" + role + ".tar",
                       max_size=MAX_ARCHIVE) as opened:
        before = os.fstat(opened.fileno())
        if before.st_size != size:
            raise ValueError("private rootfs size mismatch")
        digest = hashlib.sha256()
        for block in iter(lambda: opened.read(1024*1024), b""):
            digest.update(block)
        if digest.hexdigest() != expected_sha:
            raise ValueError("private rootfs digest changed")
        summary = _audit_tar(opened, declared_count=count)
        after = os.fstat(opened.fileno())
        if (before.st_size != after.st_size or
                before.st_mtime_ns != after.st_mtime_ns or
                before.st_ctime_ns != after.st_ctime_ns):
            raise ValueError("archive changed during metadata audit")
        return summary


def audit(base: Path):
    fd = _private_dir(Path(base))
    try:
        with _private_file(fd, PREFIX + ".receipt.json",
                           max_size=MAX_RECEIPT) as receipt:
            evidence = strict_json(receipt.read(MAX_RECEIPT+1))
        if (not isinstance(evidence, dict) or
                set(evidence) != {
                    "schema", "rootfs_files_created", "roles",
                    "legacy_container_images_recovered",
                    "rootfs_equivalent_to_original_oci_image",
                    "runnable_rollback_verified",
                    "independent_admin_custody_verified",
                    "consistent_live_snapshot_proven",
                    "private_sensitive_data_may_be_present",
                    "production_containers_or_volumes_modified",
                    "safe_to_cutover",
                } or type(evidence["schema"]) is not int or
                evidence["schema"] != 1 or
                evidence["rootfs_files_created"] is not True or
                evidence["private_sensitive_data_may_be_present"] is not True or
                any(evidence[k] is not False for k in (
                    "legacy_container_images_recovered",
                    "rootfs_equivalent_to_original_oci_image",
                    "runnable_rollback_verified",
                    "independent_admin_custody_verified",
                    "consistent_live_snapshot_proven",
                    "production_containers_or_volumes_modified",
                    "safe_to_cutover",
                ))):
            raise ValueError("private rootfs receipt untrusted")
        rows = evidence["roles"]
        if (not isinstance(rows, list) or len(rows) != 2 or
                any(not isinstance(row, dict) for row in rows) or
                {row.get("role") for row in rows} != set(ROLES)):
            raise ValueError("unexpected private rootfs role set")
        summaries = []
        for role, expected_image in ROLES.items():
            row = next(x for x in rows if x["role"] == role)
            if (set(row) != {"role", "source_image", "rootfs_tar_sha256",
                             "rootfs_tar_bytes", "tar_member_count"} or
                    row["source_image"] != expected_image):
                raise ValueError("unexpected immutable legacy source image")
            summaries.append(_verify_tar(fd, role=role,
                                         size=row["rootfs_tar_bytes"],
                                         expected_sha=row["rootfs_tar_sha256"],
                                         count=row["tar_member_count"]))
        return {
            "status": "METADATA_ONLY_HOLD",
            "audited_archives": 2,
            "all_declared_hashes_and_lengths_verified": True,
            "member_count": sum(s["member_count"] for s in summaries),
            "links_needing_review": sum(s["links_needing_review"] for s in summaries),
            "special_nodes_needing_review": sum(
                s["special_nodes_needing_review"] for s in summaries),
            "sensitive_name_categories_needing_review": sum(
                s["sensitive_name_categories_needing_review"] for s in summaries),
            "nonzero_setuid_or_setgid_entries": sum(
                s["nonzero_setuid_or_setgid_entries"] for s in summaries),
            "raw_file_names_or_contents_disclosed": False,
            "privileged_container_or_volume_access": False,
            "oci_config_and_layer_chain_restored": False,
            "runnable_rollback_verified": False,
            "independent_admin_custody_verified": False,
            "production_modified": False,
            "safe_to_cutover": False,
        }
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-custody-dir", required=True)
    args = parser.parse_args()
    try:
        report = audit(Path(args.private_custody_dir))
    except (OSError, ValueError, TypeError, KeyError, StopIteration,
            tarfile.TarError, UnicodeError, json.JSONDecodeError):
        print(json.dumps({"status": "HOLD", "legacy_images_recovered": False,
                          "runnable_rollback_verified": False,
                          "production_modified": False,
                          "safe_to_cutover": False}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
