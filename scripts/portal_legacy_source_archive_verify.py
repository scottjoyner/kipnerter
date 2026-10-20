#!/usr/bin/env python3
"""Verify PRIVATE legacy source custody receipt and archived input hashes, read-only.

Never extracts source, opens Docker, contacts production, executes build scripts,
reads live .env or uploads source. Report only bounded eligibility booleans.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile

BASE_NAME = "legacy-app-source-before-17-20261019.tar.gz"
MAX_COMPRESSED = 128 * 1024**2
MAX_SOURCE = 128 * 1024**2
MAX_MEMBER = 16 * 1024**2
MAX_FILES = 8000
MAX_RECEIPT = 16384
HEX = re.compile(r"[a-f0-9]{64}\Z")
REQUIRED = {
    "docker-compose.yml", "compose.spatial.yml", "apps/api/Dockerfile",
    "apps/api/requirements.txt", "apps/web/Dockerfile", "apps/web/package.json",
}
SKIP_DIRS = {".git", ".next", "node_modules", "__pycache__", ".venv",
             ".pytest_cache", ".cache", "dist", "build", "coverage", ".turbo"}
EXTENSIONS = {
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".css", ".html",
    ".txt", ".toml", ".yml", ".yaml", ".md", ".json", ".sh", ".svg",
    ".png", ".ico", ".webp", ".gif", ".jpeg", ".jpg", ".wasm",
}
ROOT_FILES = {"docker-compose.yml", "compose.spatial.yml"}
TREES = ("apps/api/", "apps/web/", "infra/caddy/")


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate private source receipt field")
        out[key] = value
    return out


def _private_file(folder_fd, basename, *, max_length):
    fd = os.open(basename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                 os.O_CLOEXEC, dir_fd=folder_fd)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1 or not 0 < info.st_size <= max_length):
            raise ValueError("untrusted private source custody file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def _check_private_folder(folder):
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY |
                 os.O_NOFOLLOW | os.O_CLOEXEC)
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        os.close(fd)
        raise ValueError("owner-private 0700 source custody directory required")
    return fd


def _source_entry_valid(name):
    if (not isinstance(name, str) or not name or len(name) > 4096
            or name.startswith("/") or "\\" in name or "\x00" in name):
        raise ValueError("unsafe source archive path")
    parts = name.split("/")
    if (any(not p or p in (".", "..") or p.startswith(".env") or
            p in SKIP_DIRS for p in parts)):
        raise ValueError("unsafe source archive path")
    if name in ROOT_FILES:
        return
    if not name.startswith(TREES):
        raise ValueError("source archive outside approved trees")
    filename = parts[-1].lower()
    if (filename.startswith("id_") or filename.endswith(
            (".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db",
             ".log", ".zip", ".tar", ".gz", ".env", ".sql", ".jsonl",
             ".trace", ".gguf", ".safetensors"))):
        raise ValueError("disallowed source archive filename")
    suffix = Path(filename).suffix.lower()
    if suffix not in EXTENSIONS and filename not in (
            "dockerfile", "package-lock.json", "package.json", "requirements.txt"):
        raise ValueError("disallowed source archive extension")


def _verify_receipt(receipt):
    expected = {
        "schema", "source_manifest_sha256", "source_archive_sha256",
        "source_file_count", "source_total_mib_upper_bound",
        "private_archive_created", "web_dependency_lock_present",
        "web_legacy_build_reproducibility_verified", "docker_images_recovered",
        "runnable_equivalence_tested", "prior_git_revision_authoritative",
        "secrets_included_by_design",
        "production_app_containers_or_volumes_modified", "safe_to_cutover",
    }
    if (not isinstance(receipt, dict) or set(receipt) != expected
            or type(receipt["schema"]) is not int or receipt["schema"] != 1
            or not isinstance(receipt["source_manifest_sha256"], str)
            or not HEX.fullmatch(receipt["source_manifest_sha256"])
            or not isinstance(receipt["source_archive_sha256"], str)
            or not HEX.fullmatch(receipt["source_archive_sha256"])
            or type(receipt["source_file_count"]) is not int
            or not 6 <= receipt["source_file_count"] <= MAX_FILES
            or type(receipt["source_total_mib_upper_bound"]) is not int
            or not 0 <= receipt["source_total_mib_upper_bound"] <= 128
            or type(receipt["web_dependency_lock_present"]) is not bool
            or receipt["private_archive_created"] is not True
            or any(receipt[key] is not False for key in (
                "web_legacy_build_reproducibility_verified", "docker_images_recovered",
                "runnable_equivalence_tested", "prior_git_revision_authoritative",
                "secrets_included_by_design",
                "production_app_containers_or_volumes_modified",
                "safe_to_cutover"))):
        raise ValueError("invalid source provenance claims")


def inspect(directory: Path):
    fd = _check_private_folder(Path(directory))
    try:
        with _private_file(fd, BASE_NAME + ".receipt.json",
                           max_length=MAX_RECEIPT) as rec:
            report = json.loads(rec.read(MAX_RECEIPT + 1),
                                object_pairs_hook=_unique_pairs)
        _verify_receipt(report)
        with _private_file(fd, BASE_NAME, max_length=MAX_COMPRESSED) as archive:
            first = os.fstat(archive.fileno())
            digest = hashlib.sha256()
            for part in iter(lambda: archive.read(1024*1024), b""):
                digest.update(part)
            if digest.hexdigest() != report["source_archive_sha256"]:
                raise ValueError("legacy source gzip archive digest mismatch")
            archive.seek(0)
            files = {}
            total_size = 0
            count = 0
            with tarfile.open(fileobj=archive, mode="r:gz") as tar:
                for member in tar:
                    count += 1
                    if count > MAX_FILES or not member.isfile() or (
                            member.size < 0 or member.size > MAX_MEMBER):
                        raise ValueError("unsafe archived source member")
                    _source_entry_valid(member.name)
                    if member.name in files:
                        raise ValueError("duplicate archived source filename")
                    reader = tar.extractfile(member)
                    if reader is None:
                        raise ValueError("unreadable source archive member")
                    member_digest = hashlib.sha256()
                    actual = 0
                    while part := reader.read(1024*1024):
                        actual += len(part)
                        total_size += len(part)
                        if actual > MAX_MEMBER or total_size > MAX_SOURCE:
                            raise ValueError("unbounded source archive contents")
                        member_digest.update(part)
                    if actual != member.size:
                        raise ValueError("incomplete source file")
                    files[member.name] = member_digest.digest()
            if count != report["source_file_count"] or not REQUIRED.issubset(files):
                raise ValueError("source manifest missing required build input")
            manifest = hashlib.sha256()
            for filename in sorted(files):
                manifest.update(filename.encode("utf-8") + b"\x00" + files[filename])
            if manifest.hexdigest() != report["source_manifest_sha256"]:
                raise ValueError("archived source manifest differs from receipt")
            mib_ceil = (total_size + 1024**2 - 1) // 1024**2
            if mib_ceil != report["source_total_mib_upper_bound"]:
                raise ValueError("source archive length bound differs from receipt")
            if ("apps/web/package-lock.json" in files) != (
                    report["web_dependency_lock_present"]):
                raise ValueError("source web lock receipt inconsistent")
            last = os.fstat(archive.fileno())
            if (first.st_size != last.st_size or
                    first.st_mtime_ns != last.st_mtime_ns or
                    first.st_ctime_ns != last.st_ctime_ns):
                raise ValueError("private source archive changed during verification")
        return {
            "status": "SOURCE_CUSTODY_VERIFIED_NOT_RUNNABLE",
            "source_manifest_compared_to_archive": True,
            "source_archive_digest_verified": True,
            "archived_source_files_checked": count,
            "essential_build_inputs_present": True,
            "web_dependency_lock_present": report["web_dependency_lock_present"],
            "legacy_git_revision_authoritative": False,
            "original_oci_images_recovered": False,
            "runnable_rollback_verified": False,
            "actual_build_reproduced": False,
            "independent_admin_custody_verified": False,
            "source_bytes_or_paths_disclosed": False,
            "production_modified": False,
            "safe_to_cutover": False,
        }
    finally:
        os.close(fd)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-custody-dir", required=True)
    args = parser.parse_args()
    try:
        result = inspect(Path(args.private_custody_dir))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            tarfile.TarError, EOFError, json.JSONDecodeError):
        print(json.dumps({"status": "HOLD", "safe_to_cutover": False,
                          "original_oci_images_recovered": False,
                          "production_modified": False}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
