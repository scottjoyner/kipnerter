#!/usr/bin/env python3
"""One-shot private preservation of running legacy container root filesystems.

Requires a pre-existing private custody directory. Does not restart, stop,
rebuild, commit, tag, pull or replace containers. Does NOT produce OCI images
or a valid rollback, and may capture baked-in sensitive files.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

BACKUPS = Path.home()/".local/state/kipnerter-release/state-backups"
SOURCE_RECEIPT = "legacy-app-source-before-17-20261019.tar.gz.receipt.json"
ROLES = (
    ("kipnerter-api-1", "kipnerter-api", "sha256:7efc68e54ff1289ee2033440ea0ee176962e3a57e0d24e091a2365ca769d5860"),
    ("kipnerter-web-1", "kipnerter-web", "sha256:5dfd3de1d45260b826d52eb107df8398e872121c9d98ade02540f3917fc78726"),
)
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
MAX_BYTES = 2 * 1024**3
MIN_FREE = 20 * 1024**3
FILENAME = "legacy-rootfs-before-17-20261019"
RECEIPT = FILENAME + ".receipt.json"

def run(args, timeout=12):
    result = subprocess.run(args, capture_output=True, text=True,
                            timeout=timeout, check=True)
    if len(result.stdout) > 4096:
        raise ValueError("unbounded metadata response")
    return result.stdout.strip()

def custody(base):
    if (base.is_symlink() or not base.is_dir() or
        base.stat().st_uid != os.getuid() or
        stat.S_IMODE(base.stat().st_mode) != 0o700):
        raise ValueError("private 0700 custody directory required")

def inspect(role, ref, old_image):
    fmt=('{{.State.Running}}|{{.Image}}|{{.Config.Image}}|'
         '{{index .Config.Labels "com.docker.compose.project"}}|'
         '{{len .Mounts}}|{{.SizeRw}}|{{.SizeRootFs}}|{{.State.StartedAt}}')
    raw=run(["docker","inspect","--size","--format",fmt,role]).split("|")
    if (len(raw)!=8 or raw[0]!="true" or raw[1]!=old_image or
        raw[2]!=ref or raw[3]!="kipnerter" or raw[4]!="0" or
        not raw[5].isdigit() or not raw[6].isdigit() or
        not 0 <= int(raw[5]) <= 512*1024**2 or
        not 0 < int(raw[6]) <= MAX_BYTES or not raw[7].endswith("Z")):
        raise ValueError("legacy role not stable/isolated")
    return (raw[1], raw[7], int(raw[6]), int(raw[5]))

def preflight(base):
    custody(base)
    src=base/SOURCE_RECEIPT
    if src.is_symlink() or not src.is_file() or src.stat().st_size>16384:
        raise ValueError("verified source receipt required")
    info=json.loads(src.read_text())
    if (info.get("schema")!=1 or info.get("safe_to_cutover") is not False or
        info.get("docker_images_recovered") is not False or
        info.get("private_archive_created") is not True):
        raise ValueError("source custody receipt not valid")
    if (any(os.path.lexists(base/(FILENAME+"-"+r+".tar"))
            for r,_,_ in ROLES) or os.path.lexists(base/RECEIPT) or
            any(base.glob(".legacy-rootfs-incomplete-*"))):
        raise ValueError("one-shot rootfs custody target or partial already present")
    before={}
    total=0
    for role,ref,old_image in ROLES:
        state=inspect(role,ref,old_image)
        total+=state[2]
        try:
            run(["docker","image","inspect","--format","{{.Id}}",old_image])
        except subprocess.CalledProcessError:
            pass
        else:
            raise ValueError("original image available: use exact image retention")
        tag=run(["docker","image","inspect","--format","{{.Id}}",ref])
        if not IMAGE.fullmatch(tag) or tag==old_image:
            raise ValueError("old tag has changed or image qualification inconsistent")
        before[role]=state
    free=shutil.disk_usage(base).free
    if free < MIN_FREE + 2*total:
        raise ValueError("insufficient private export headroom")
    return before

def stream_export(role, base):
    fd,path=tempfile.mkstemp(prefix=".legacy-rootfs-incomplete-",dir=base)
    os.fchmod(fd,0o600)
    digest=hashlib.sha256()
    size=0
    child=None
    try:
        with os.fdopen(fd,"wb") as out:
            child=subprocess.Popen(["docker","export",role],stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
            assert child.stdout is not None
            for block in iter(lambda:child.stdout.read(1024*1024),b""):
                size+=len(block)
                if size>MAX_BYTES:
                    child.kill()
                    raise ValueError("rootfs export larger than 2 GiB")
                digest.update(block)
                out.write(block)
            if child.wait(timeout=150)!=0 or not size:
                raise ValueError("Docker rootfs export failed")
            out.flush()
            os.fsync(out.fileno())
        with tarfile.open(path,mode="r:") as tar:
            count=0
            for item in tar:
                count+=1
                if count>200000 or item.size>MAX_BYTES or not (
                    item.isfile() or item.isdir() or item.issym() or
                    item.islnk() or item.isfifo() or item.ischr() or item.isblk()
                ):
                    raise ValueError("unacceptable Docker export stream")
        if not count:
            raise ValueError("empty rootfs tar")
        return path, size, digest.hexdigest(), count
    except BaseException:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        # Incomplete private file retained for operator investigation, never reused.
        raise

def preserve(base=BACKUPS):
    before=preflight(base)
    reports=[]
    for role,ref,old_image in ROLES:
        tmp,size,digest,count=stream_export(role,base)
        if inspect(role,ref,old_image)!=before[role]:
            raise ValueError("running container changed during export")
        target=base/(FILENAME+"-"+role+".tar")
        if os.path.lexists(target):
            raise ValueError("rootfs target changed during preservation")
        os.replace(tmp,target)
        reports.append({"role":role,"source_image":old_image,
                        "rootfs_tar_sha256":digest,"rootfs_tar_bytes":size,
                        "tar_member_count":count})
    info={"schema":1,"rootfs_files_created":True,"roles":reports,
          "legacy_container_images_recovered":False,
          "rootfs_equivalent_to_original_oci_image":False,
          "runnable_rollback_verified":False,
          "independent_admin_custody_verified":False,
          "consistent_live_snapshot_proven":False,
          "private_sensitive_data_may_be_present":True,
          "production_containers_or_volumes_modified":False,
          "safe_to_cutover":False}
    fd=os.open(base/RECEIPT,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"w") as handle:
        json.dump(info,handle,sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {"status":"PRIVATE_ROOTFS_SOURCE_PRESERVED_NOT_OCI_IMAGE",
            "role_count":len(reports),"total_rootfs_mib_upper_bound":
            (sum(x["rootfs_tar_bytes"] for x in reports)+1024**2-1)//1024**2,
            "private_receipt_saved":True,"safe_to_cutover":False,
            "original_oci_images_recovered":False,"production_modified":False}

def main():
    try:
        print(json.dumps(preserve(),sort_keys=True))
        return 0
    except (OSError,ValueError,TypeError,subprocess.SubprocessError,tarfile.TarError):
        print(json.dumps({"status":"HOLD","private_partial_may_exist":True,
                          "old_images_recovered":False,"production_containers_or_volumes_modified":False,
                          "safe_to_cutover":False},sort_keys=True))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
