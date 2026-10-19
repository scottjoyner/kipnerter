#!/usr/bin/env python3
"""Read-only baseline of the existing Kipnerter production Compose cutover target.

No Docker writes, no database queries, no object reads, no environment dump,
and no credentials or unredacted private paths emitted. This is a necessary
legacy-to-managed migration inventory, NOT a migration or GO authorization.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

APP_ROOT=Path("/opt/kipnerter")
SOURCE_SHA=bytes((173, 76, 255, 230, 225, 254, 108, 101, 157, 151, 228, 138, 150, 210, 32, 242, 240, 84, 60, 85)).hex()
EXPECTED=(
    "kipnerter-api-1", "kipnerter-caddy-1", "kipnerter-web-1",
    "kipnerter-spatial-api-1", "kipnerter-spatial-worker-1",
    "kipnerter-spatial-postgres-1","kipnerter-spatial-minio-1",
)
VOLUMES={
    "kipnerter-spatial-postgres-1": ("spatial_postgres_data", "/var/lib/postgresql/data"),
    "kipnerter-spatial-minio-1": ("spatial_minio_data", "/data"),
}
SHA256=re.compile(r"sha256:[a-f0-9]{64}\Z")
MAX_RESPONSE=128_000


def output(cmd: list[str], timeout: int=10)->str:
    proc=subprocess.run(cmd,capture_output=True,text=True,check=True,timeout=timeout)
    if len(proc.stdout)>MAX_RESPONSE:
        raise ValueError("Docker metadata output exceeds bound")
    return proc.stdout.strip()


def safe_files(root: Path)->dict:
    """Read only tracked Compose bytes; never read or hash the private .env."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("legacy root absent or a symlink")
    result={}
    for name in ("docker-compose.yml","compose.spatial.yml"):
        file=root/name
        if file.is_symlink() or not file.is_file() or file.stat().st_size>1024*1024:
            raise ValueError("missing or oversized legacy compose source")
        digest=hashlib.sha256(file.read_bytes()).hexdigest()
        result[name]=digest
    env=root/".env"
    result["private_env_present"]=env.is_file() and not env.is_symlink()
    result["private_env_0600_or_more_restrictive"]=(
        result["private_env_present"] and stat.S_IMODE(env.stat().st_mode)&0o077==0
    )
    return result


def match_mounts(raw: object, suffix: str, target: str)->bool:
    if not isinstance(raw,list) or len(raw)>40:
        return False
    matches=[x for x in raw if isinstance(x,dict) and x.get("Destination")==target]
    return (len(matches)==1 and matches[0].get("Type")=="volume" and
            isinstance(matches[0].get("Name"),str) and
            matches[0]["Name"].endswith("_"+suffix) and
            matches[0].get("RW") is True)


def qualified(records:dict, mounts:dict, source:dict, backup_receipt:bool,
              pointer_exists:bool)->dict:
    if not isinstance(records,dict):
        raise ValueError("invalid legacy inventory")
    missing=sorted(set(EXPECTED)-set(records))
    invalid=[]
    images=[]
    for name in EXPECTED:
        if name not in records:
            continue
        entry=records[name]
        if not isinstance(entry,dict):
            invalid.append(name+"_INVALID_METADATA");continue
        image=entry.get("image")
        if (entry.get("running") is not True or
                not isinstance(image,str) or not SHA256.fullmatch(image) or
                entry.get("project")!="kipnerter" or
                not isinstance(entry.get("service"),str) or
                not entry.get("service") or
                entry.get("working_directory")!="/opt/kipnerter"):
            invalid.append(name+"_COMPOSE_IDENTITY")
        else:
            images.append((name,image,entry["service"]))
    for container,(suffix,target) in VOLUMES.items():
        if not match_mounts(mounts.get(container),suffix,target):
            invalid.append(container+"_STATE_VOLUME_UNQUALIFIED")
    if not source.get("private_env_0600_or_more_restrictive"):
        invalid.append("LEGACY_PRIVATE_ENV_PERMISSIONS")
    if pointer_exists:
        invalid.append("LEGACY_MANAGED_POINTER_ALREADY_PRESENT")
    digest=hashlib.sha256(
        json.dumps(sorted(images),separators=(",",":")).encode()
    ).hexdigest() if len(images)==len(EXPECTED) else None
    return {
        "baseline_format":1,
        "expected_legacy_containers":len(EXPECTED),
        "running_compose_containers_verified":len(images),
        "missing_container_roles":missing,
        "invalid_checks":sorted(invalid),
        "container_image_service_fingerprint_sha256":digest,
        "legacy_compose_files_sha256":{
            name: source.get(name) for name in ("docker-compose.yml","compose.spatial.yml")
        },
        "private_source_staging_receipt_present":bool(source.get("stage_present")),
        "private_state_backup_receipt_present":backup_receipt,
        "managed_current_pointer_present":pointer_exists,
        "candidate_ready_for_independent_review":
            not missing and not invalid and bool(source.get("stage_present")) and backup_receipt,
        "previous_releasable_git_revision_cryptographically_identified":False,
        "backup_independent_custody":False,
        "minio_snapshot_write_fenced":False,
        "oidc_real_browser_login_verified":False,
        "safe_to_cutover":False,
        "production_files_or_containers_modified":False,
    }


def main()->int:
    try:
        source=safe_files(APP_ROOT)
        private=Path.home()/".local/state/kipnerter-release"
        source["stage_present"]=(
            (private/"verified"/SOURCE_SHA/".portal-staged.json").is_file() and
            (private/"verified"/SOURCE_SHA/"gateway-api/Dockerfile").is_file()
        )
        receipt=(private/"state-backups"/
                 ("ios17-precutover-"+SOURCE_SHA[:12])/"snapshot-receipt.json")
        backup_ok=(not receipt.is_symlink() and receipt.is_file() and
                   receipt.stat().st_uid==os.getuid() and
                   stat.S_IMODE(receipt.stat().st_mode)==0o600)
        found=output(["docker","ps","--format","{{.Names}}"])
        names=set(found.splitlines())
        records={}
        mounts={}
        for name in EXPECTED:
            if name not in names:
                continue
            raw=output(["docker","inspect","--format",
                '{{json .}}',name])
            val=json.loads(raw)
            # Never emit private Config.Env, Mount Sources or labels.
            labels=val.get("Config",{}).get("Labels") or {}
            records[name]={
                "running":val.get("State",{}).get("Running"),
                "image":val.get("Image"),
                "project":labels.get("com.docker.compose.project"),
                "service":labels.get("com.docker.compose.service"),
                "working_directory":labels.get("com.docker.compose.project.working_dir"),
            }
            if name in VOLUMES:
                mounts[name]=val.get("Mounts")
        # No attempt to treat the immutable source staging as the prior
        # running application revision; only a separately attested baseline
        # can establish that authority.
        current=(APP_ROOT/"current")
        report=qualified(records,mounts,source,backup_ok,
                         pointer_exists=current.exists() or current.is_symlink())
        print(json.dumps(report,sort_keys=True))
        return 0 if report["candidate_ready_for_independent_review"] else 3
    except (OSError,ValueError,TypeError,KeyError,
            subprocess.SubprocessError,json.JSONDecodeError) as exc:
        print(json.dumps({"status":"NO_GO","reason_class":type(exc).__name__,
                          "safe_to_cutover":False,
                          "production_files_or_containers_modified":False},
                         sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
