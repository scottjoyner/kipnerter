#!/usr/bin/env python3
"""One-shot private production state snapshot. No service shutdown or volume writes.

PostgreSQL snapshot is a transaction-consistent logical dump. MinIO archive
copies raw live backing files; it may NOT be point-in-time consistent. A
successful copy MUST NOT be treated as a MinIO restore, S3-level backup,
independent custody, or permission to upgrade the running production stack.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

SOURCE_SHA = "ad4cffe6e1fe6c659d97e48a96d220f2f0543c55"
POSTGRES = "kipnerter-spatial-postgres-1"
MINIO = "kipnerter-spatial-minio-1"
MAX_BYTES = 3 * 1024**3


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as reader:
        for block in iter(lambda: reader.read(1024*1024), b""):
            total += len(block)
            if total > MAX_BYTES:
                raise ValueError("bounded backup archive exceeded limit")
            digest.update(block)
    if total == 0:
        raise ValueError("empty backup archive")
    return digest.hexdigest(), total


def inspect_tar(path: Path) -> tuple[int, int]:
    """Read all regular members, enforcing bounded paths and no links."""
    count = 0
    total = 0
    with tarfile.open(path, "r:") as reader:
        for member in reader:
            if (member.name.startswith("/") or "\\" in member.name or
                    any(part in ("", "..") for part in member.name.split("/")) or
                    member.issym() or member.islnk() or
                    not (member.isdir() or member.isfile())):
                raise ValueError("unsafe raw object-store archive entry")
            count += 1
            if count > 300000:
                raise ValueError("too many object-store archive entries")
            if member.isfile():
                total += member.size
                if total > MAX_BYTES:
                    raise ValueError("object-store copy exceeded size limit")
                stream = reader.extractfile(member)
                if stream is None:
                    raise ValueError("unreadable tar member")
                while stream.read(1024 * 1024):
                    pass
    if count < 2:
        raise ValueError("empty object-store archive")
    return count, total


def ensure_private(base: Path) -> None:
    if base.exists():
        if (base.is_symlink() or base.resolve() != base or
                not base.is_dir() or base.stat().st_uid != os.getuid() or
                base.stat().st_mode & 0o077):
            raise ValueError("backup parent directory is not private")
    else:
        base.mkdir(mode=0o700, parents=False)
    os.chmod(base, 0o700)


def snapshot(base: Path, *, staged: Path) -> dict:
    # Source-receipt presence is necessary, not independent custody.
    if (not (staged / ".portal-staged.json").is_file() or
            not (staged / "gateway-api/Dockerfile").is_file()):
        raise ValueError("exact portal source was not privately staged")
    if shutil.disk_usage(base).free < 12 * 1024**3:
        raise ValueError("insufficient private backup filesystem capacity")
    dest = base / ("ios17-precutover-" + SOURCE_SHA[:12])
    # Permanent one-shot directory blocks silent retry after ambiguous errors.
    dest.mkdir(mode=0o700, exist_ok=False)
    os.chmod(dest, 0o700)

    db = dest / "postgresql.custom"
    with db.open("xb") as output:
        os.chmod(db, 0o600)
        subprocess.run(["docker","exec","-u","postgres",POSTGRES,
            "pg_dump","-Fc","--no-owner","--no-privileges",
            "-U","kipnerter","-d","kipnerter"],stdout=output,
            stderr=subprocess.DEVNULL,check=True,timeout=180)
        output.flush()
        os.fsync(output.fileno())
    db_hash, db_bytes = sha256_file(db)
    with db.open("rb") as raw:
        subprocess.run(["docker","exec","-i",POSTGRES,
                        "pg_restore","--list"],stdin=raw,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       check=True,timeout=60)

    store = dest / "minio-raw-live.tar"
    with store.open("xb") as output:
        os.chmod(store, 0o600)
        subprocess.run(["docker","cp",f"{MINIO}:/data","-"],stdout=output,
            stderr=subprocess.DEVNULL,check=True,timeout=180)
        output.flush()
        os.fsync(output.fileno())
    store_hash, store_bytes = sha256_file(store)
    store_members, store_contents = inspect_tar(store)

    receipt = {
        "schema": 1,
        "source_staging_sha": SOURCE_SHA,
        "postgres_logical_dump_sha256": db_hash,
        "postgres_dump_bytes": db_bytes,
        "postgres_archive_toc_parsed": True,
        "minio_live_raw_copy_sha256": store_hash,
        "minio_copy_bytes": store_bytes,
        "minio_archive_members_checked": store_members,
        "minio_payload_bytes_inspected": store_contents,
        "postgres_database_restore_rehearsed": False,
        "minio_s3_level_restore_rehearsed": False,
        "minio_point_in_time_consistency_verified": False,
        "external_independent_custody_verified": False,
        "production_containers_changed": False,
        "production_volumes_written": False,
        "safe_to_cutover": False,
    }
    path = dest / "snapshot-receipt.json"
    with path.open("x", encoding="utf-8") as output:
        json.dump(receipt, output, sort_keys=True, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.chmod(path, 0o600)
    return receipt


def main() -> int:
    try:
        home = Path.home() / ".local/state/kipnerter-release"
        ensure_private(home)
        backup_parent = home / "state-backups"
        ensure_private(backup_parent)
        staged = home / "verified" / SOURCE_SHA
        receipt = snapshot(backup_parent, staged=staged)
        # Never publish database content, object keys or secret material.
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (OSError,ValueError,subprocess.SubprocessError,tarfile.TarError) as exc:
        print(json.dumps({"status":"HOLD","error_class":type(exc).__name__,
                          "one_shot_attempt_may_exist":True,
                          "production_containers_changed":False,
                          "safe_to_cutover":False},sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
