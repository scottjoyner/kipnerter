#!/usr/bin/env python3
"""One-shot read-only fresh production PostgreSQL dump -> RAM-only offhost restore.

Operator opt-in, fixed x1-370 host, fixed authenticated Tailscale principal,
exact loaded original production PostgreSQL image, no production Docker writes.
PostgreSQL pg_dump is DB transaction-consistent only; MinIO is NOT included,
no writer fence/cross-service PIT/custodian/release authorization is asserted.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time

from scripts import portal_private_production_backup_offhost_rehearsal as backup
from scripts import portal_state_restore_rehearsal as restore

HOST = "x1-370"
PG = "kipnerter-spatial-postgres-1"
IMAGE = backup.IMAGES[PG]
REMOTE = backup.PROD_SSH
MAX_DUMP = 8 * 1024 * 1024
MIN_DUMP = 1000
REMOTE_COMMAND = (
    "docker exec -u postgres kipnerter-spatial-postgres-1 "
    "pg_dump -Fc --no-owner --no-privileges -U kipnerter -d kipnerter"
)
REMOTE_ARGS = ["timeout", "100s", "tailscale", "ssh", REMOTE, REMOTE_COMMAND]


def validate_scratch() -> None:
    if socket.gethostname() != HOST:
        raise ValueError("unauthorized scratch restore host")
    if not backup.private_tmpfs_ready():
        raise ValueError("RAM-backed private scratch not verified")
    backup.verify_image_id(PG)
    backup.read_only_remote_identity()


def bounded_archive(pipe, target: Path, *, monotonic=time.monotonic) -> tuple[int,str]:
    """Cap writes before copy and hash the exact bytes of this one output stream."""
    start = monotonic()
    sha = hashlib.sha256()
    size = 0
    with target.open('xb') as out:
        os.fchmod(out.fileno(),stat.S_IRUSR|stat.S_IWUSR)
        while True:
            if monotonic()-start > 105:
                raise ValueError('bounded live PostgreSQL dump timed out')
            block = pipe.read(256 * 1024)
            if not block:
                break
            if not isinstance(block, bytes):
                raise ValueError('untrusted nonbinary PostgreSQL dump stream')
            size += len(block)
            if size > MAX_DUMP:
                raise ValueError('production dump exceeds 8 MiB bound')
            out.write(block)
            sha.update(block)
    if not MIN_DUMP <= size <= MAX_DUMP:
        raise ValueError('missing or truncated production dump')
    with target.open('rb') as raw:
        if raw.read(5) != b'PGDMP':
            raise ValueError('not a PostgreSQL custom-format dump')
    return size,sha.hexdigest()


def fetch_current_dump(root: Path, *, popen=subprocess.Popen) -> tuple[Path,int,str]:
    """Source is read-only `pg_dump`; capture stderr privately and never log it."""
    target=root/'postgresql.custom'
    proc=popen(REMOTE_ARGS,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
    try:
        if proc.stdout is None:
            raise ValueError('no production dump pipe')
        size,digest=bounded_archive(proc.stdout,target)
        if proc.wait(timeout=15)!=0:
            raise ValueError('source PostgreSQL dump failed')
        return target,size,digest
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=6)
        if proc.stdout is not None:
            proc.stdout.close()


def execute() -> dict:
    validate_scratch()
    started=datetime.now(timezone.utc).isoformat()
    initial=restore.image_of
    try:
        with tempfile.TemporaryDirectory(prefix='kipnerter-current-pg-restore-',dir='/dev/shm') as temp:
            root=Path(temp)
            if root.stat().st_mode & 0o077:
                raise ValueError('temporary production backup directory not private')
            dump,size,digest=fetch_current_dump(root)
            # Physical production container identities may have drifted during
            # the dump. Fail closed, even if local scratch image remains pinned.
            backup.read_only_remote_identity()
            restore.image_of=lambda name: IMAGE if name == PG else (_ for _ in ()).throw(ValueError('unknown source image role'))
            tables=restore.scratch_postgres(dump,expected=digest,expected_bytes=size)
            if type(tables) is not int or not 0 < tables <= 10000:
                raise ValueError('unexpected restored table count')
        if root.exists():
            raise ValueError('temporary production data not deleted')
        return {
            'status':'FRESH_PRODUCTION_POSTGRES_TMPFS_RESTORE_PASS_NOT_CUTOVER',
            'captured_start_utc':started,
            'captured_end_utc':datetime.now(timezone.utc).isoformat(),
            'source':'live_postgres_read_only_pg_dump',
            'archive_bytes':size,'archive_sha256':digest,
            'restored_user_tables':tables,
            'actual_running_image_id':IMAGE,
            'production_data_retained_offhost':False,
            'production_services_or_volumes_changed':False,
            'database_transaction_snapshot_consistent':True,
            'minio_included_in_snapshot':False,
            'production_writes_fenced':False,
            'cross_service_point_in_time_consistent':False,
            'independent_custody_verified':False,
            'real_oidc_browser_login_verified':False,
            'safe_to_cutover':False,
            'release_gate':'NO_GO',
        }
    finally:
        restore.image_of=initial


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    result={'status':'DRY_RUN_NO_REMOTE_OR_DOCKER_ACTION','release_gate':'NO_GO',
            'safe_to_cutover':False,'production_services_or_volumes_changed':False}
    if not args.execute:
        print(json.dumps(result,sort_keys=True));return 3
    try:
        result=execute()
        code=0
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError) as error:
        result={'status':'HOLD','error_class':type(error).__name__,
                'release_gate':'NO_GO','safe_to_cutover':False,
                'production_services_or_volumes_changed':False}
        code=2
    print(json.dumps(result,sort_keys=True))
    return code


if __name__=='__main__':
    sys.exit(main())
