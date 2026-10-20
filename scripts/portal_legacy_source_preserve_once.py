#!/usr/bin/env python3
"""One-shot, private, bounded copy of production legacy web/API build inputs.

Source-only archive: excludes credentials, data, Docker volumes, dependency
caches, derived builds. NEVER claims former OCI image bit-equivalence.
Does not use Docker, read private .env or change the live application.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile

ROOT=Path("/opt/kipnerter")
DESTINATION=(Path.home()/".local/state/kipnerter-release/state-backups")
FILENAME="legacy-app-source-before-17-20261019.tar.gz"
RECEIPT=FILENAME+".receipt.json"
MAX_FILES=8000
MAX_TOTAL=128*1024**2
MAX_FILE=16*1024**2
SKIP_DIRECTORIES={
    ".git",".next","node_modules","__pycache__", ".venv",
    ".pytest_cache",".cache","dist","build","coverage",".turbo"
}
EXTENSIONS={
    ".py",".js",".jsx",".mjs",".cjs",".ts",".tsx",".css",".html",
    ".txt",".toml",".yml",".yaml",".md",".json",".sh",".svg",
    ".png",".ico",".webp",".gif",".jpeg",".jpg",".wasm"
}
SOURCE_TREES=("apps/api","apps/web","infra/caddy")
ROOT_FILES=("docker-compose.yml","compose.spatial.yml")


def allowed(relative:Path)->bool:
    parts=relative.parts
    if not parts or any(x in ("",".","..") for x in parts):
        return False
    if any(x.startswith(".env") or x in SKIP_DIRECTORIES for x in parts):
        return False
    filename=relative.name.lower()
    if (filename.startswith("id_") or filename.endswith(
            (".pem",".key",".p12",".pfx",".sqlite",".sqlite3",".db",
             ".log",".zip",".tar",".gz",".env",".sql",".jsonl",
             ".trace",".gguf",".safetensors"))):
        return False
    return relative.suffix.lower() in EXTENSIONS or filename in (
        "dockerfile","package-lock.json","package.json","requirements.txt"
    )


def gather(root:Path)->list[tuple[Path,Path]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("untrusted production source root")
    output=[]
    total=0
    for name in ROOT_FILES:
        relative=Path(name)
        file=root/relative
        if file.is_symlink() or not file.is_file():
            raise ValueError("essential legacy Compose source missing")
        output.append((relative,file))
    for base in SOURCE_TREES:
        prefix=Path(base)
        path=root/prefix
        if path.is_symlink() or not path.is_dir():
            raise ValueError("essential legacy build tree missing")
        for folder,dirs,files in os.walk(path,followlinks=False):
            parent=Path(folder)
            approved=[]
            for d in sorted(dirs):
                nested=parent/d
                if nested.is_symlink():
                    raise ValueError("linked build context directory")
                if d.startswith(".") or d in SKIP_DIRECTORIES:
                    continue
                approved.append(d)
            dirs[:]=approved
            for filename in sorted(files):
                item=parent/filename
                rel=item.relative_to(root)
                if item.is_symlink():
                    raise ValueError("linked build context file")
                if not allowed(rel):
                    continue
                if not item.is_file():
                    raise ValueError("nonregular build context file")
                output.append((rel,item))
    for relative,file in output:
        st=file.stat()
        if not stat.S_ISREG(st.st_mode) or not 0<=st.st_size<=MAX_FILE:
            raise ValueError("invalid source file type or size")
        total+=st.st_size
        if total>MAX_TOTAL or len(output)>MAX_FILES:
            raise ValueError("production source exceeds retention bound")
    names=[p.as_posix() for p,_ in output]
    if len(names)!=len(set(names)):
        raise ValueError("duplicate archived source entry")
    for required in ("apps/api/Dockerfile","apps/api/requirements.txt",
                     "apps/web/Dockerfile","apps/web/package.json"):
        if required not in names:
            raise ValueError("essential legacy app build input unavailable")
    return sorted(output,key=lambda row:row[0].as_posix())


def source_hash(files:list[tuple[Path,Path]])->tuple[str,int]:
    dig=hashlib.sha256()
    total=0
    for relative,item in files:
        b=hashlib.sha256()
        with item.open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):
                b.update(chunk)
                total+=len(chunk)
        dig.update(relative.as_posix().encode()+b"\0"+b.digest())
    return dig.hexdigest(),total


def private_dir(root:Path)->None:
    if (root.is_symlink() or not root.is_dir() or
            root.stat().st_uid!=os.getuid() or
            stat.S_IMODE(root.stat().st_mode)!=0o700):
        raise ValueError("untrusted existing backup custody")


def snapshot(root:Path,base:Path)->dict:
    private_dir(base)
    entries=gather(root)
    digest,total=source_hash(entries)
    output=base/FILENAME
    receipt=base/RECEIPT
    if output.exists() or receipt.exists() or output.is_symlink() or receipt.is_symlink():
        raise ValueError("one-shot source backup already present")
    # Never overwrite on failure. Partial file is retained for operator review
    # and must never be treated as a successful source backup.
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as out:
        with tarfile.open(fileobj=out,mode="w:gz") as archive:
            for rel,item in entries:
                archive.add(item,arcname=rel.as_posix(),recursive=False)
        out.flush()
        os.fsync(out.fileno())
    tarhash=hashlib.sha256()
    with output.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            tarhash.update(chunk)
    with tarfile.open(output,"r:gz") as archive:
        actual={x.name for x in archive}
        if actual!={p.as_posix() for p,_ in entries}:
            raise ValueError("source tar entries changed")
    info={
        "schema":1,
        "source_manifest_sha256":digest,
        "source_archive_sha256":tarhash.hexdigest(),
        "source_file_count":len(entries),
        "source_total_mib_upper_bound":(total+1024**2-1)//1024**2,
        "private_archive_created":True,
        "web_dependency_lock_present":any(p.as_posix()=="apps/web/package-lock.json" for p,_ in entries),
        "web_legacy_build_reproducibility_verified":False,
        "docker_images_recovered":False,
        "runnable_equivalence_tested":False,
        "prior_git_revision_authoritative":False,
        "secrets_included_by_design":False,
        "production_app_containers_or_volumes_modified":False,
        "safe_to_cutover":False,
    }
    writefd=os.open(receipt,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(writefd,"w") as f:
        json.dump(info,f,sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    return info


def preflight(root:Path,base:Path)->dict:
    """No writes. Determine source eligibility and any interrupted prior attempt."""
    private_dir(base)
    entries=gather(root)
    archive_exists=os.path.lexists(base/FILENAME)
    receipt_exists=os.path.lexists(base/RECEIPT)
    return {
        "source_preflight":"PASS" if not archive_exists and not receipt_exists else "HOLD",
        "source_file_count":len(entries),
        "web_dependency_lock_present":any(p.as_posix()=="apps/web/package-lock.json" for p,_ in entries),
        "web_legacy_build_reproducibility_verified":False,
        "previous_attempt_archive_present":archive_exists,
        "previous_attempt_receipt_present":receipt_exists,
        "source_data_or_secrets_read":False,
        "production_app_containers_or_volumes_modified":False,
        "safe_to_cutover":False,
    }


def main()->int:
    try:
        if sys.argv[1:]==["--inspect-only"]:
            report=preflight(ROOT,DESTINATION)
            print(json.dumps(report,sort_keys=True))
            return 0 if report["source_preflight"]=="PASS" else 3
        if len(sys.argv)!=1:
            raise ValueError("unknown retention command")
        report=snapshot(ROOT,DESTINATION)
        print(json.dumps(report,sort_keys=True))
        return 0
    except (OSError,ValueError,tarfile.TarError) as exc:
        allowed={"untrusted production source root",
                 "essential legacy Compose source missing",
                 "essential legacy build tree missing",
                 "linked build context directory",
                 "linked build context file",
                 "nonregular build context file",
                 "invalid source file type or size",
                 "production source exceeds retention bound",
                 "duplicate archived source entry",
                 "essential legacy app build input unavailable",
                 "untrusted existing backup custody",
                 "one-shot source backup already present",
                 "source tar entries changed",
                 "unknown retention command"}
        reason=str(exc) if isinstance(exc,ValueError) and str(exc) in allowed else "unspecified"
        print(json.dumps({
            "status":"HOLD","reason_class":type(exc).__name__,
            "bounded_reason_code":reason,
            "ambiguous_partial_source_copy_may_exist":True,
            "production_app_containers_or_volumes_modified":False,
            "safe_to_cutover":False,
        },sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
