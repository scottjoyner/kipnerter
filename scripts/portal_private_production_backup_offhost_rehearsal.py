#!/usr/bin/env python3
"""Operator-opt-in, RAM-only off-host check of ONE existing production backup.

Uses only fixed, SHA-256-pinned archive identities, the existing Tailscale SSH
non-root production principal, and the exact imported production storage images.
No remote writes, source DB queries, network forwarding, production Docker
changes, permanent backup copies, or public release authority.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile

from scripts import portal_state_restore_rehearsal as restore

TEST_HOST = "x1-370"
PROD_SSH = "kipnerter@100.82.144.33"
SOURCE = "ad4cffe6e1fe6c659d97e48a96d220f2f0543c55"
REMOTE_BASE = "/home/kipnerter/.local/state/kipnerter-release/state-backups/ios17-precutover-" + SOURCE[:12] + "/"
ARCHIVES = {
    "snapshot-receipt.json": (774, "a527dc38335725b3e6558a95d6e1eab35b50a251e0ef3c67189d146d5e38973b"),
    "postgresql.custom": (52881, "50740e17083559bfe69c2d3d882372f85f0cad7364edcd31dc2b7d69da058a18"),
    "minio-raw-live.tar": (84992, "aaf02ecb6efc835742a8c88e7009b911c9d4b1c9a9ca52220db7e5b015050b30"),
}
IMAGES = {
    "kipnerter-spatial-postgres-1": "sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5",
    "kipnerter-spatial-minio-1": "sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e",
}


def private_tmpfs_ready(path=Path('/dev/shm')):
    if path.is_symlink() or not path.is_dir():
        return False
    # /dev/shm is normally mode 01777: world-writable but sticky.
    mode=path.stat().st_mode
    if (mode & 0o002) and not (mode & stat.S_ISVTX):
        return False
    try:
        info=Path('/proc/self/mountinfo').read_text()
        for line in info.splitlines():
            first,sep,second=line.partition(' - ')
            if sep and len(first.split())>4 and first.split()[4]==str(path):
                return second.split()[0]=='tmpfs'
    except (OSError,IndexError,ValueError):
        return False
    return False


def fetched_bytes(name):
    if name not in ARCHIVES:
        raise ValueError('unknown fixed backup name')
    size,digest=ARCHIVES[name]
    # head caps output even if remote bytes were replaced by a much larger file.
    remote='head -c '+str(size+1)+' '+REMOTE_BASE+name
    result=subprocess.run(['timeout','20s','tailscale','ssh',PROD_SSH,remote],
                          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=24,check=False)
    if (result.returncode != 0 or len(result.stdout)!=size or
            hashlib.sha256(result.stdout).hexdigest()!=digest):
        raise ValueError('remote private backup does not match pinned original')
    return result.stdout


def verify_image_id(name):
    expected=IMAGES[name]
    result=subprocess.run(['docker','image','inspect','--format','{{.Id}}',expected],
                          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=8,check=False)
    if result.returncode or result.stdout.decode().strip()!=expected:
        raise ValueError('exact archived storage image not imported')


def read_only_remote_identity():
    command='docker inspect --format "{{.Name}} {{.Image}}" kipnerter-spatial-postgres-1 kipnerter-spatial-minio-1'
    result=subprocess.run(['timeout','16s','tailscale','ssh',PROD_SSH,command],
                          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20,check=False)
    required={"/"+k+" "+v for k,v in IMAGES.items()}
    if result.returncode or set(result.stdout.decode().strip().splitlines())!=required:
        raise ValueError('actual running production image identities differ')


def run_rehearsal():
    if socket.gethostname()!=TEST_HOST or restore.SOURCE!=SOURCE:
        raise ValueError('unapproved rehearsal host/source binding')
    if not private_tmpfs_ready():
        raise ValueError('verified RAM-backed temporary storage required')
    for container in IMAGES:
        verify_image_id(container)
    read_only_remote_identity()
    original_image_of=restore.image_of
    try:
        # Existing rigorously tested private FD verifier must use only these
        # imported image IDs, not attempt to inspect production containers here.
        restore.image_of=lambda name: IMAGES[name]
        with tempfile.TemporaryDirectory(prefix='kipnerter-actual-backup-rehearsal-',dir='/dev/shm') as tmp:
            root=Path(tmp)
            if root.stat().st_mode & 0o077:
                raise ValueError('untrusted scratch directory permissions')
            folder=root/('ios17-precutover-'+SOURCE[:12])
            folder.mkdir(mode=0o700)
            for name in ARCHIVES:
                payload=fetched_bytes(name)
                path=folder/name
                with path.open('xb') as stream:
                    os.fchmod(stream.fileno(),stat.S_IRUSR|stat.S_IWUSR)
                    stream.write(payload)
                del payload
            receipt=restore.load_receipt(folder)
            count=restore.scratch_postgres(folder/'postgresql.custom',
                 expected=receipt['postgres_logical_dump_sha256'],
                 expected_bytes=receipt['postgres_dump_bytes'])
            if type(count) is not int or not 0 < count <= 10000:
                raise ValueError('restored user table count invalid')
            ready=restore.scratch_minio(folder/'minio-raw-live.tar',root,
                 expected=receipt['minio_live_raw_copy_sha256'],
                 expected_bytes=receipt['minio_copy_bytes'])
            if ready is not True:
                raise ValueError('scratch raw-data MinIO server did not start')
        # Returning only after TemporaryDirectory has removed the raw backups.
        return {"status":"OLD_REAL_BACKUP_SCRATCH_RESTORE_PASS_NOT_RELEASE_AUTHORIZATION",
                    "source_staging_sha":SOURCE,"postgres_user_tables_restored":count,
                    "minio_raw_backup_server_started":True,
                    "backup_archive_hashes_verified":True,
                    "exact_running_storage_images_verified":True,
                    "backup_files_transferred_to_ram_only":True}
    finally:
        restore.image_of=original_image_of


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    report={"status":"HOLD","release_gate":"NO_GO","safe_to_cutover":False,
            "production_database_backup_current":False,
            "production_data_point_in_time_verified":False,
            "minio_live_object_inventory_verified":False,
            "independent_administrative_custody":False,
            "real_oidc_browser_login_verified":False,
            "production_containers_or_volumes_modified":False}
    if not args.execute:
        report['status']='DRY_RUN_NO_REMOTE_OR_DOCKER_OPERATIONS'
        print(json.dumps(report,sort_keys=True))
        return 3
    try:
        result=run_rehearsal()
        report.update(result)
        returncode=0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        report['error_class']=type(exc).__name__
        returncode=2
    # Successful return occurs only after TemporaryDirectory cleanup.
    # Error paths do not claim verified erasure without a separate witness.
    report['temporary_backup_bytes_retained']=False if returncode==0 else None
    print(json.dumps(report,sort_keys=True))
    return returncode

if __name__=='__main__':
    sys.exit(main())
