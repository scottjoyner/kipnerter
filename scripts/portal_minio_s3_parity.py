#!/usr/bin/env python3
"""Read-only S3 metadata parity: live MinIO against offline raw snapshot.

No object bodies, bucket names, secret URLs or access keys in tool output.
Scratch MinIO uses an isolated network namespace and no production volumes.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import select
import sys
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time

SOURCE="ad4cffe6e1fe6c659d97e48a96d220f2f0543c55"
BUCKET="kipnerter-artifacts"
IMAGE=re.compile(r"^sha256:[a-f0-9]{64}$")
MAX_ARCHIVE = 3 * 1024 ** 3  # same bound as snapshot writer
MAX_EXTRACT_BYTES = 3 * 1024 ** 3
MAX_ENTRIES = 300_000
MAX_PATH = 512
MIN_SPARE_BYTES = 128 * 1024 ** 2
ALIAS='MC_HOST_release="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@127.0.0.1:9000" '

def run(argv, *, env=None, timeout=25, capture=False):
    result=subprocess.run(argv,check=True,timeout=timeout,env=env,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    if capture and len(result.stdout)>2_000_000:
        raise ValueError("S3 metadata response too large")
    return result.stdout.decode("utf-8","strict") if capture else ""

def json_lines(raw):
    records=[]
    for line in raw.splitlines():
        item=json.loads(line)
        if not isinstance(item,dict) or item.get("status")=="error" or item.get("error"):
            raise ValueError("untrusted S3 listing")
        records.append(item)
        if len(records)>10000:raise ValueError("S3 listing too large")
    return records

def summarize(buckets, objects):
    present=any(str(x.get("key","")).rstrip("/")==BUCKET
                for x in json_lines(buckets))
    if not present and objects:
        raise ValueError("object listing without bucket")
    entries=[]
    if present:
        for x in json_lines(objects):
            if x.get("type") not in ("file","object"):
                continue
            key=x.get("key")
            size=x.get("size")
            etag=x.get("etag") or ""
            if not isinstance(key,str) or not isinstance(size,int) or size<0 or not isinstance(etag,str):
                raise ValueError("ambiguous object metadata")
            entries.append((key,size,etag))
    entries.sort()
    digest=hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest()
    return (present,len(entries),digest)

def inventory(container):
    prefix=["docker","exec",container,"sh","-c"]
    roots=run(prefix+[ALIAS+"mc ls --json release"],capture=True,timeout=30)
    have=any(str(x.get("key","")).rstrip("/")==BUCKET for x in json_lines(roots))
    body=run(prefix+[ALIAS+"mc ls --recursive --json release/"+BUCKET],
             capture=True,timeout=45) if have else ""
    return summarize(roots,body)

# Byte-level verification is deliberately opt-in. All S3 object payload
# bytes flow only from local Docker to the production host process, never to
# GitHub, chat logs, disk, or remote clients. Enforce caps before and DURING
# reads, even if a concurrent source mutation changes a declared object size.
MAX_OBJECTS=32
MAX_SINGLE_OBJECT=32*1024*1024
MAX_ALL_OBJECTS=64*1024*1024


def listed_objects(container):
    prefix=["docker","exec",container,"sh","-c"]
    roots=run(prefix+[ALIAS+"mc ls --json release"],capture=True,timeout=30)
    if not any(str(x.get("key","")).rstrip("/")==BUCKET for x in json_lines(roots)):
        raise ValueError("expected first-party S3 bucket missing")
    result=run(prefix+[ALIAS+"mc ls --recursive --json release/"+BUCKET],
               capture=True,timeout=45)
    items={}
    total=0
    for row in json_lines(result):
        if row.get("type") not in ("file","object"):
            continue
        name=row.get("key")
        size=row.get("size")
        if (not isinstance(name,str) or not name or
                any(ord(ch)<32 for ch in name) or
                len(name)>1024 or not isinstance(size,int) or
                type(size) is bool or size<0 or size>MAX_SINGLE_OBJECT or
                name in items):
            raise ValueError("untrusted or oversized S3 object listing")
        items[name]=size
        total+=size
        if len(items)>MAX_OBJECTS or total>MAX_ALL_OBJECTS:
            raise ValueError("bounded S3 object content limit exceeded")
    return sorted(items.items())


def streamed_object_sha(container, name, expected_size):
    # Prefix is fixed; key is passed as POSIX shell positional argument, not
    # interpolated into executable text. No credentials or bytes are logged.
    if (not isinstance(name,str) or not name or
            not isinstance(expected_size,int) or
            expected_size<0 or expected_size>MAX_SINGLE_OBJECT):
        raise ValueError("invalid bounded object")
    argv=["docker","exec",container,"sh","-c",
          ALIAS+'mc cat "$1"', "sh", "release/"+BUCKET+"/"+name]
    p=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                       bufsize=0)
    digest=hashlib.sha256()
    amount=0
    expires=time.monotonic()+45
    try:
        while True:
            remaining=expires-time.monotonic()
            if remaining<=0:
                raise ValueError("S3 object download timed out")
            ready,_,_=select.select([p.stdout],[],[],remaining)
            if not ready:
                raise ValueError("S3 object read timed out")
            chunk=os.read(p.stdout.fileno(),1024*1024)
            if not chunk:
                break
            amount+=len(chunk)
            if amount>expected_size or amount>MAX_SINGLE_OBJECT:
                raise ValueError("S3 object changed size during read")
            digest.update(chunk)
        if p.wait(timeout=3)!=0 or amount!=expected_size:
            raise ValueError("S3 object read failed or mismatched length")
        return digest.hexdigest()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)
        if p.stdout:
            p.stdout.close()


def content_inventory(container):
    objects=listed_objects(container)
    witnessed=[]
    for key,expected in objects:
        witnessed.append((key,expected,streamed_object_sha(container,key,expected)))
    # Keys and hashes remain in the local process, never emitted in logs.
    fingerprint=hashlib.sha256(
        json.dumps(witnessed,ensure_ascii=False,separators=(",",":")).encode()
    ).hexdigest()
    return len(witnessed),fingerprint


def backup_checked(folder):
    # This local restore rehearsal must use exactly the private one-shot
    # archive the operator already verified, not a linked or public copy.
    receipt = folder / "snapshot-receipt.json"
    if (receipt.is_symlink() or not receipt.is_file() or
            receipt.stat().st_uid != os.getuid() or receipt.stat().st_mode & 0o077
            or receipt.stat().st_size > 65536):
        raise ValueError("untrusted private snapshot receipt")
    r = json.loads(receipt.read_text("utf-8"))
    if (not isinstance(r, dict) or type(r.get("schema")) is not int or
            r.get("schema") != 1 or r.get("source_staging_sha") != SOURCE
            or r.get("safe_to_cutover") is not False
            or r.get("minio_s3_level_restore_rehearsed") is not False):
        raise ValueError("wrong snapshot identity")
    dest = folder / "minio-raw-live.tar"
    if (dest.is_symlink() or not dest.is_file() or
            dest.stat().st_uid != os.getuid() or dest.stat().st_mode & 0o077
            or not 0 < dest.stat().st_size <= MAX_ARCHIVE):
        raise ValueError("untrusted private snapshot archive")
    expected = r.get("minio_live_raw_copy_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("invalid snapshot digest")
    h = hashlib.sha256()
    size = 0
    with dest.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            if size > MAX_ARCHIVE:
                raise ValueError("snapshot archive exceeds bounded size")
            h.update(block)
    if type(r.get("minio_copy_bytes")) is not int or size != r["minio_copy_bytes"] or h.hexdigest() != expected:
        raise ValueError("snapshot digest or length drift")
    return dest


def extract(archive, root):
    # The private raw copy is not a trusted tar archive merely because the
    # receipt's SHA matches it. Bound expansion before any filesystem writes.
    if (root.is_symlink() or not root.is_dir() or any(root.iterdir())
            or archive.is_symlink() or not archive.is_file()
            or archive.stat().st_size > MAX_ARCHIVE):
        raise ValueError("unsafe or nonempty scratch restore root")
    count = 0
    total = 0
    names = set()
    with tarfile.open(archive, "r:") as src:
        for member in src:
            name = member.name
            parts = name.split("/")
            if (not isinstance(name, str) or len(name) > MAX_PATH
                    or name.startswith("/") or "\\" in name
                    or any(part in ("", ".", "..") for part in parts)
                    or (name != "data" and not name.startswith("data/"))
                    or name in names or member.issym() or member.islnk()
                    or not (member.isfile() or member.isdir())
                    or member.size < 0):
                raise ValueError("unsafe scratch archive")
            names.add(name)
            count += 1
            if count > MAX_ENTRIES:
                raise ValueError("too many raw snapshot entries")
            if member.isfile():
                total += member.size
                if total > MAX_EXTRACT_BYTES:
                    raise ValueError("snapshot expansion exceeds bound")
        if count < 2 or total == 0:
            raise ValueError("invalid scratch archive contents")
        if total + MIN_SPARE_BYTES > shutil.disk_usage(root).free:
            raise ValueError("insufficient private scratch restore capacity")
        src.extractall(root, filter="data")
    result = root / "data"
    if result.is_symlink() or not result.is_dir():
        raise ValueError("missing scratch volume")
    return result


def restored_inventory(archive,folder, inspector=inventory):
    image=run(["docker","inspect","--format","{{.Image}}",
               "kipnerter-spatial-minio-1"],capture=True).strip()
    if not IMAGE.fullmatch(image): raise ValueError("unverified image")
    name="kipnerter-s3-verify-"+secrets.token_hex(5)
    env=dict(os.environ, MINIO_ROOT_USER=secrets.token_urlsafe(20),
             MINIO_ROOT_PASSWORD=secrets.token_urlsafe(32))
    started=False
    with tempfile.TemporaryDirectory(prefix="minio-parity-",dir=folder) as scratch:
        target=extract(archive,Path(scratch))
        try:
            run(["docker","run","-d","--rm","--name",name,"--network","none",
                 "--pids-limit","128","--memory","1024m",
                 "--user",f"{os.getuid()}:{os.getgid()}",
                 "--read-only","--tmpfs","/tmp:rw,nosuid,size=67108864",
                 "--mount",f"type=bind,src={target},dst=/data",
                 "-e","MINIO_ROOT_USER","-e","MINIO_ROOT_PASSWORD",
                 "-e","HOME=/tmp",image,"server","/data"],
                 env=env,timeout=30)
            started=True
            for _ in range(65):
                try:
                    run(["docker","exec",name,"curl","--fail","--silent",
                         "--max-time","2","http://127.0.0.1:9000/minio/health/ready"],
                        timeout=4)
                    break
                except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
                    time.sleep(.25)
            else: raise ValueError("scratch MinIO not ready")
            return inspector(name)
        finally:
            if started:
                subprocess.run(["docker","rm","-f",name],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=25)

def main():
    try:
        folder=Path.home()/".local/state/kipnerter-release/state-backups"/(
            "ios17-precutover-"+SOURCE[:12])
        if folder.is_symlink() or not folder.is_dir() or folder.stat().st_mode & 0o077:
            raise ValueError("untrusted private backup path")
        archive=backup_checked(folder)
        live=inventory("kipnerter-spatial-minio-1")
        restored=restored_inventory(archive,folder)
        matched=(live==restored)
        body_match=False
        bodies_checked=False
        count=0
        if len(sys.argv)==2 and sys.argv[1]=="--content-verify":
            if not matched or not live[0]:
                raise ValueError("S3 metadata drift forbids byte-level attestation")
            live_bodies=content_inventory("kipnerter-spatial-minio-1")
            # Validate the live listing did not change during streaming.
            if inventory("kipnerter-spatial-minio-1")!=live:
                raise ValueError("live S3 metadata changed during content check")
            restore_bodies=restored_inventory(archive,folder,
                                              inspector=content_inventory)
            count=live_bodies[0]
            body_match=(live_bodies==restore_bodies and count==live[1])
            bodies_checked=True
        elif len(sys.argv)!=1:
            raise ValueError("unsupported read-only verifier invocation")
        print(json.dumps({
            "live_bucket_present":live[0],"restored_bucket_present":restored[0],
            "live_object_count":live[1],"restored_object_count":restored[1],
            "s3_bucket_object_metadata_parity":matched,
            "s3_object_bodies_retrieved":bodies_checked,
            "s3_object_body_count_checked":count,
            "s3_object_sha256_body_parity":body_match,
            "source_writes_fenced_during_snapshot":False,
            "independent_external_custody":False,
            "scratch_network":"none",
            "production_services_modified":False,"safe_to_cutover":False},
            sort_keys=True))
        return 0 if matched and (not bodies_checked or body_match) else 3
    except (OSError,ValueError,TypeError,KeyError,tarfile.TarError,
            subprocess.SubprocessError,json.JSONDecodeError) as e:
        print(json.dumps({"result":"HOLD","reason_class":type(e).__name__,
              "production_services_modified":False,"safe_to_cutover":False},
              sort_keys=True))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
