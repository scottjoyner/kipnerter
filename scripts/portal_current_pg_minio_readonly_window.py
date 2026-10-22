#!/usr/bin/env python3
"""Opt-in fresh PG + MinIO source read during ONE bounded observation window.

Never claims a coordinated point-in-time snapshot: production writers were
NOT fenced. Bounded private tmpfs copies are deleted; only counts and hashes
leave the production host. No public release/restore authorization is issued.
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
import tarfile
import tempfile

from scripts import portal_current_postgres_tmpfs_restore as pg
from scripts import portal_minio_s3_parity as s3
from scripts import portal_private_minio_offhost_s3_parity as s3w
from scripts import portal_private_production_backup_offhost_rehearsal as backup
from scripts import portal_state_restore_rehearsal as recovery
from scripts import portal_state_snapshot_once as snapshot

MAX_RAW_MINIO_BYTES = 16 * 1024 * 1024
MIN_RAW_MINIO_BYTES = 1024
REMOTE_MINIO_COMMAND = 'docker cp kipnerter-spatial-minio-1:/data -'
MINIO_SSH_ARGS = ['timeout','90s','tailscale','ssh',backup.PROD_SSH,REMOTE_MINIO_COMMAND]


def prereqs():
    if socket.gethostname()!=backup.TEST_HOST or not backup.private_tmpfs_ready():
        raise ValueError('only private x1-370 tmpfs rehearsal authorized')
    for role in backup.IMAGES:
        backup.verify_image_id(role)
    backup.read_only_remote_identity()


def fresh_minio_archive(root: Path, *, popen=subprocess.Popen):
    target=root/'minio-live-copy.tar'
    proc=popen(MINIO_SSH_ARGS,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
    count=0
    h=hashlib.sha256()
    try:
        if proc.stdout is None:raise ValueError('no MinIO backup stdout')
        with target.open('xb') as file:
            os.fchmod(file.fileno(),stat.S_IRUSR|stat.S_IWUSR)
            while True:
                block=proc.stdout.read(128*1024)
                if not block:break
                if not isinstance(block,bytes):raise ValueError('nonbinary raw backup')
                count+=len(block)
                if count>MAX_RAW_MINIO_BYTES:
                    raise ValueError('MinIO copy exceeds 16MiB cap')
                h.update(block);file.write(block)
        if proc.wait(timeout=12)!=0:raise ValueError('source MinIO Docker copy failed')
    finally:
        if proc.poll() is None:
            proc.kill();proc.wait(timeout=6)
        if proc.stdout is not None:proc.stdout.close()
    if not MIN_RAW_MINIO_BYTES<=count<=MAX_RAW_MINIO_BYTES:
        raise ValueError('missing raw MinIO archive')
    # Bounded tar validation *before* extraction, including link/type/path caps.
    members,payload_bytes=snapshot.inspect_tar(target)
    if members<2 or payload_bytes<1:
        raise ValueError('raw archive missing content')
    return target,count,h.hexdigest(),members


def restored_minio_content(archive: Path, root: Path):
    original=s3.run
    expected=backup.IMAGES['kipnerter-spatial-minio-1']
    def exact_original_image(argv,*,env=None,timeout=25,capture=False):
        if argv==['docker','inspect','--format','{{.Image}}','kipnerter-spatial-minio-1']:
            return expected
        return original(argv,env=env,timeout=timeout,capture=capture)
    def inspect(container):
        meta=s3.inventory(container)
        if (meta[0] is not True or not 0<meta[1]<=s3.MAX_OBJECTS):
            raise ValueError('restored S3 inventory missing')
        bodies=s3.content_inventory(container)
        if (bodies[0]!=meta[1] or s3.inventory(container)!=meta):
            raise ValueError('restored S3 changed during inspection')
        return meta,bodies
    try:
        s3.run=exact_original_image
        return s3.restored_inventory(archive,root,inspector=inspect)
    finally:
        s3.run=original


def execute():
    prereqs()
    now=lambda:datetime.now(timezone.utc).isoformat()
    start=now()
    first=s3w.checked_live_read()  # bytes hashed ONLY on production
    previous=recovery.image_of
    try:
        with tempfile.TemporaryDirectory(prefix='kipnerter-current-pg-minio-window-',dir='/dev/shm') as td:
            root=Path(td)
            if root.stat().st_mode&0o077:raise ValueError('nonprivate scratch directory')
            fresh_pg,pg_bytes,pg_hash=pg.fetch_current_dump(root)
            recovery.image_of=lambda name:backup.IMAGES[name]
            pg_tables=recovery.scratch_postgres(fresh_pg,expected=pg_hash,expected_bytes=pg_bytes)
            if type(pg_tables) is not int or not 0<pg_tables<=10000:
                raise ValueError('unexpected table count')
            minio_tar,minio_bytes,minio_hash,tar_members=fresh_minio_archive(root)
            meta,content=restored_minio_content(minio_tar,root)
            backup.read_only_remote_identity()
            second=s3w.checked_live_read()
            if first!=second:
                raise ValueError('live MinIO S3 changed across paired observations')
            if (meta!=(True,first['object_count'],first['metadata_digest']) or
                    content!=(first['object_count'],first['content_digest'])):
                raise ValueError('fresh raw MinIO copy lacks S3 object parity')
        if root.exists():raise ValueError('backup scratch not deleted')
        return {
            'status':'FRESH_PG_AND_MINIO_READONLY_OBSERVATION_WINDOW_PASS_NOT_ATOMIC',
            'observation_start_utc':start,
            'observation_end_utc':now(),
            'postgres_dump_sha256':pg_hash,
            'postgres_dump_bytes':pg_bytes,
            'postgres_restored_user_tables':pg_tables,
            'minio_raw_archive_sha256':minio_hash,
            'minio_raw_archive_bytes':minio_bytes,
            'minio_archive_members':tar_members,
            'minio_restored_object_count':content[0],
            'minio_restored_content_fingerprint_sha256':content[1],
            'minio_live_metadata_fingerprint_sha256':first['metadata_digest'],
            'live_s3_pre_and_post_identical':True,
            'fresh_data_retained_offhost':False,
            'production_services_or_volumes_changed':False,
            'postgres_transaction_consistent':True,
            'minio_source_writes_fenced':False,
            'postgres_source_writes_fenced':False,
            'cross_service_point_in_time_consistent':False,
            'independent_administrative_custody':False,
            'real_oidc_browser_login_verified':False,
            'safe_to_cutover':False,
            'release_gate':'NO_GO',
        }
    finally:
        recovery.image_of=previous


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    state={'status':'DRY_RUN_NO_PRODUCTION_ACCESS','safe_to_cutover':False,
           'release_gate':'NO_GO','production_services_or_volumes_changed':False}
    if not args.execute:
        print(json.dumps(state,sort_keys=True));return 3
    try:
        state=execute();code=0
    except (OSError,ValueError,TypeError,KeyError,tarfile.TarError,subprocess.SubprocessError) as e:
        state={'status':'HOLD','error_class':type(e).__name__,'safe_to_cutover':False,
               'release_gate':'NO_GO','production_services_or_volumes_changed':False}
        code=2
    print(json.dumps(state,sort_keys=True));return code

if __name__=='__main__':
    sys.exit(main())
