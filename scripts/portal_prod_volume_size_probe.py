#!/usr/bin/env python3
"""Size-only metadata probe of the two live stateful Kipnerter Docker volumes.

No backups, SQL queries, MinIO GETs, service changes, network requests,
exports or file writes. Docker 'du -sk' traverses mounted filesystem metadata
and reports aggregate KiB; no individual filenames are printed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

EXPECTED = {
    "postgres": ("kipnerter-spatial-postgres-1", "/var/lib/postgresql/data"),
    "minio": ("kipnerter-spatial-minio-1", "/data"),
}
SIZE = re.compile(r"^([0-9]{1,15})\s+(/[^\n\r\t ]+)$")


def parse_du(output: str, path: str) -> int:
    match = SIZE.fullmatch(output.strip())
    if not match or match.group(2) != path:
        raise ValueError("untrusted or malformed du response")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("empty stateful storage is not independently explained")
    return amount * 1024


def check_capacity(postgres_bytes: int, minio_bytes: int, free_bytes: int) -> dict:
    if min(postgres_bytes, minio_bytes, free_bytes) < 0:
        raise ValueError("invalid disk capacity")
    aggregate = postgres_bytes + minio_bytes
    # Snapshot feasibility is only an upper bound: pg_dump compression,
    # MinIO consistency, encryption, ongoing writes and remote custody are
    # NOT qualified by free disk. Reserve 12GiB + twice raw estimate.
    margin = 12 * 1024**3
    conservative = free_bytes >= 2 * aggregate + margin
    return {
        "postgres_data_gib_rounded_up": (postgres_bytes + 1024**3 - 1)//(1024**3),
        "minio_data_gib_rounded_up": (minio_bytes + 1024**3 - 1)//(1024**3),
        "free_gib_rounded_down": free_bytes//(1024**3),
        "conservative_local_backup_capacity": conservative,
        "stateful_volume_reads_only": True,
        "live_db_or_object_contents_extracted": False,
        "backup_written": False,
        "restore_rehearsed": False,
        "external_backup_custody_verified": False,
        "safe_to_cutover": False,
        "production_modified": False,
    }


def main() -> int:
    try:
        sizes: dict[str,int] = {}
        for name, (container, path) in EXPECTED.items():
            process = subprocess.run(["docker","exec",container,"du","-sk",path],
                capture_output=True, text=True, check=True, timeout=45)
            if len(process.stdout)>250 or len(process.stderr)>250:
                raise ValueError("unexpected excessive disk-size output")
            sizes[name]=parse_du(process.stdout,path)
        free=shutil.disk_usage(Path("/opt/kipnerter")).free
        print(json.dumps(check_capacity(sizes["postgres"],sizes["minio"],free),
                         sort_keys=True))
        return 0
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print(json.dumps({"result":"NO_GO","reason_class":type(exc).__name__,
                          "backup_written":False,"safe_to_cutover":False,
                          "production_modified":False},sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
