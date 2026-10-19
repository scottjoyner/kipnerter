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
import subprocess
import tarfile
import tempfile
import time

SOURCE="ad4cffe6e1fe6c659d97e48a96d220f2f0543c55"
BUCKET="kipnerter-artifacts"
IMAGE=re.compile(r"^sha256:[a-f0-9]{64}$")
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

def backup_checked(folder):
    r=json.loads((folder/"snapshot-receipt.json").read_text("utf-8"))
    if r.get("schema")!=1 or r.get("source_staging_sha")!=SOURCE:
        raise ValueError("wrong snapshot identity")
    dest=folder/"minio-raw-live.tar"
    if dest.is_symlink():
        raise ValueError("symlinked snapshot")
    h=hashlib.sha256()
    with dest.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            h.update(block)
    if h.hexdigest()!=r.get("minio_live_raw_copy_sha256"):
        raise ValueError("snapshot digest drift")
    return dest

def extract(archive,root):
    with tarfile.open(archive,"r:") as src:
        count=0
        for member in src:
            if (member.name.startswith("/") or "\\" in member.name or
                ".." in member.name.split("/") or member.issym() or member.islnk()
                or not (member.isfile() or member.isdir())):
                raise ValueError("unsafe scratch archive")
            count+=1
        if count<2 or count>300000:
            raise ValueError("invalid scratch archive length")
        src.extractall(root,filter="data")
    result=root/"data"
    if result.is_symlink() or not result.is_dir():
        raise ValueError("missing scratch volume")
    return result

def restored_inventory(archive,folder):
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
            return inventory(name)
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
        print(json.dumps({
            "live_bucket_present":live[0],"restored_bucket_present":restored[0],
            "live_object_count":live[1],"restored_object_count":restored[1],
            "s3_bucket_object_metadata_parity":matched,
            "s3_object_bodies_retrieved":False,
            "source_writes_fenced_during_snapshot":False,
            "independent_external_custody":False,
            "scratch_network":"none",
            "production_services_modified":False,"safe_to_cutover":False},
            sort_keys=True))
        return 0 if matched else 3
    except (OSError,ValueError,TypeError,KeyError,tarfile.TarError,
            subprocess.SubprocessError,json.JSONDecodeError) as e:
        print(json.dumps({"result":"HOLD","reason_class":type(e).__name__,
              "production_services_modified":False,"safe_to_cutover":False},
              sort_keys=True))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
