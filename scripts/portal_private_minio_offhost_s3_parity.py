#!/usr/bin/env python3
"""Read-only live-vs-old-backup S3 object-byte parity without raw data egress.

Operator opt-in. Live S3 object bytes are hashed only on production, never
sent over SSH. The previously captured private raw MinIO backup is read over
SSH into x1-370's RAM-backed /dev/shm and verified against pinned hashes.
Scratch MinIO is network-disabled and removed afterward. This does not fence
writes, prove point-in-time consistency, or authorize public deployment.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from typing import Any

from scripts import portal_minio_s3_parity as s3
from scripts import portal_private_production_backup_offhost_rehearsal as backup

NAME = 'kipnerter-spatial-minio-1'
IMAGE = backup.IMAGES[NAME]
MAX_REMOTE_OUTPUT = 4096
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
LIVE_BEGIN = r'''
try:
    before = inventory("kipnerter-spatial-minio-1")
    if (before[0] is not True or not 0 < before[1] <= MAX_OBJECTS):
        raise ValueError("source bucket absent or object count unbounded")
    bodies = content_inventory("kipnerter-spatial-minio-1")
    after = inventory("kipnerter-spatial-minio-1")
    if before != after or bodies[0] != before[1]:
        raise ValueError("live S3 changed or object body coverage incomplete")
    print(json.dumps({"status":"READ_ONLY_S3_CONTENT_ATTESTED",
                      "bucket_present":before[0], "object_count":before[1],
                      "metadata_digest":before[2],"content_digest":bodies[1],
                      "writes_fenced":False,"safe_to_cutover":False},sort_keys=True))
except Exception as exc:
    print(json.dumps({"status":"HOLD","error_class":type(exc).__name__,
                      "writes_fenced":False,"safe_to_cutover":False},sort_keys=True))
'''


def live_source() -> str:
    code = Path(s3.__file__).read_text('utf-8')
    marker='if __name__=="__main__":'
    if code.count(marker) != 1:
        raise ValueError('unrecognized source of read-only S3 helper')
    # Strip any main() invocation; only fixed read-only inventory() and
    # content_inventory() are callable by the bounded remote witness.
    return code.split(marker,1)[0] + '\n' + LIVE_BEGIN


def checked_live_read(*, command_runner=subprocess.run) -> dict[str, Any]:
    source = live_source().encode('utf-8')
    p = command_runner(['timeout','100s','tailscale','ssh',backup.PROD_SSH,'python3 -'],
                       input=source,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                       timeout=105,check=False)
    if p.returncode or not 0 < len(p.stdout) <= MAX_REMOTE_OUTPUT:
        raise ValueError('remote S3 witness missing or overlong')
    # Strict JSON: never trust extra/fake success lines or duplicate keys.
    def unique(pairs):
        output={}
        for k,v in pairs:
            if k in output:raise ValueError('duplicated witness field')
            output[k]=v
        return output
    report=json.loads(p.stdout,object_pairs_hook=unique)
    if (type(report) is not dict or set(report)!={
            'status','bucket_present','object_count','metadata_digest',
            'content_digest','writes_fenced','safe_to_cutover'}
            or report['status']!='READ_ONLY_S3_CONTENT_ATTESTED'
            or report['bucket_present'] is not True
            or type(report['object_count']) is not int
            or not 0 < report['object_count'] <= s3.MAX_OBJECTS
            or any(type(report.get(k)) is not str or DIGEST.fullmatch(report[k]) is None
                   for k in ('metadata_digest','content_digest'))
            or report['writes_fenced'] is not False
            or report['safe_to_cutover'] is not False):
        raise ValueError('untrusted remote S3 witness result')
    return report


def restored_raw_s3() -> tuple[tuple, tuple]:
    if not backup.private_tmpfs_ready():
        raise ValueError('private RAM-backed scratch filesystem not verified')
    backup.verify_image_id(NAME)
    original = s3.run
    with tempfile.TemporaryDirectory(prefix='kipnerter-real-minio-s3-parity-',dir='/dev/shm') as tmp:
        root=Path(tmp)
        if root.stat().st_mode & 0o077:
            raise ValueError('temporary scratch directory not private')
        folder=root/('ios17-precutover-'+backup.SOURCE[:12]);folder.mkdir(mode=0o700)
        for name in ('snapshot-receipt.json','minio-raw-live.tar'):
            data=backup.fetched_bytes(name)
            with (folder/name).open('xb') as f:
                os.fchmod(f.fileno(),0o600)
                f.write(data)
            del data
        archive=s3.backup_checked(folder)
        # Running production container does not exist on the scratch host.
        # Intercept only this EXACT read-only identity request, and use the
        # independently verified, locally imported original production image.
        def exact_image(argv,*,env=None,timeout=25,capture=False):
            if argv==['docker','inspect','--format','{{.Image}}',NAME]:
                return IMAGE
            return original(argv,env=env,timeout=timeout,capture=capture)
        s3.run=exact_image
        try:
            def single_scratch_inventory(container):
                metadata=s3.inventory(container)
                if metadata[0] is not True or not 0 < metadata[1] <= s3.MAX_OBJECTS:
                    raise ValueError('restored S3 bucket absent/empty')
                bodies=s3.content_inventory(container)
                if bodies[0] != metadata[1] or s3.inventory(container)!=metadata:
                    raise ValueError('restored metadata changed during object reads')
                return metadata,bodies
            restored=s3.restored_inventory(archive,root,inspector=single_scratch_inventory)
            return restored
        finally:
            s3.run=original


def execute() -> dict[str,Any]:
    if socket.gethostname()!=backup.TEST_HOST or backup.SOURCE!=s3.SOURCE:
        raise ValueError('wrong host or backup identity')
    if not backup.private_tmpfs_ready():
        raise ValueError('no qualified tmpfs')
    backup.verify_image_id(NAME)
    backup.read_only_remote_identity()
    first=checked_live_read()
    metadata,contents=restored_raw_s3()
    # Re-read live S3 after scratch testing. This bounds change detection but
    # DOES NOT mean writers were stopped or that the old archive was atomic.
    second=checked_live_read()
    if first!=second:
        raise ValueError('live S3 witness changed during recovery comparison')
    if (metadata!=(True,first['object_count'],first['metadata_digest']) or
            contents!=(first['object_count'],first['content_digest'])):
        raise ValueError('old backup differs from current live S3 inventory')
    return {'status':'PREVIOUS_PRODUCTION_BACKUP_S3_CONTENT_PARITY_PASS_NOT_PIT',
            'source_staging_sha':backup.SOURCE,
            'bucket_present':True,'object_count':first['object_count'],
            'metadata_fingerprint_sha256':first['metadata_digest'],
            'object_content_fingerprint_sha256':first['content_digest'],
            'source_writes_fenced':False,'point_in_time_verified':False,
            'current_backup_freshness_verified':False,
            'independent_custody_verified':False,
            'production_modified':False,'production_data_uploaded_to_github':False,
            'safe_to_cutover':False,'release_gate':'NO_GO'}


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    result={'status':'DRY_RUN_NO_REMOTE_OR_DOCKER_ACTIONS','safe_to_cutover':False,
            'release_gate':'NO_GO','production_modified':False}
    if not args.execute:
        print(json.dumps(result,sort_keys=True));return 3
    try:
        result=execute()
        code=0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,
            subprocess.SubprocessError) as err:
        result={'status':'HOLD','error_class':type(err).__name__,
                'safe_to_cutover':False,'release_gate':'NO_GO',
                'production_modified':False}
        code=2
    print(json.dumps(result,sort_keys=True))
    return code

if __name__=='__main__':
    sys.exit(main())
