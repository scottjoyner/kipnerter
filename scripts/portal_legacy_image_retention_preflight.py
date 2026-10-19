#!/usr/bin/env python3
"""Read-only, bounded app-image rollback preflight on live legacy Compose.

Docker inspect/image inspect only. No Docker save/load, no downloads,
containers, secret/env inspection, database access, or production mutations.
Image availability on one daemon is NOT durable off-host rollback custody.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

EXPECTED=(
    "kipnerter-api-1",
    "kipnerter-caddy-1",
    "kipnerter-web-1",
    "kipnerter-spatial-api-1",
    "kipnerter-spatial-worker-1",
    "kipnerter-spatial-postgres-1",
    "kipnerter-spatial-minio-1",
)
IMAGE=re.compile(r"sha256:[a-f0-9]{64}\Z")
MAX_IMAGE_BYTES=15*1024**3
MIN_REMAINING_BYTES=20*1024**3
MAX_RESPONSE=64000


def command(args: list[str], *, timeout=10)->str:
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout,check=True)
    if len(p.stdout)>MAX_RESPONSE:
        raise ValueError("excessive Docker metadata")
    return p.stdout.strip()


def validate(containers: dict, images: dict, free: int)->dict:
    if not isinstance(containers,dict) or set(containers)!=set(EXPECTED):
        raise ValueError("missing or unexpected production container")
    if not isinstance(images,dict) or len(images)>len(EXPECTED):
        raise ValueError("invalid image metadata")
    normalized=[]
    seen=set()
    logical=0
    for name in EXPECTED:
        row=containers[name]
        if not isinstance(row,dict):
            raise ValueError("invalid container identity")
        image=row.get("image")
        if (row.get("running") is not True or row.get("project")!="kipnerter" or
                row.get("working_dir")!="/opt/kipnerter" or
                not isinstance(row.get("service"),str) or not row["service"] or
                not isinstance(image,str) or not IMAGE.fullmatch(image)):
            raise ValueError("unverified legacy Compose image identity")
        normalized.append((name,image,row["service"]))
        size=images.get(image)
        if type(size) is not int or not 0<size<=MAX_IMAGE_BYTES:
            raise ValueError("missing image or implausible disk-size metadata")
        if image not in seen:
            logical+=size
            seen.add(image)
        if logical>MAX_IMAGE_BYTES:
            raise ValueError("image recovery bound exceeded")
    if type(free) is not int or free<0:
        raise ValueError("invalid free storage")
    # docker image Size is logical and can include shared layers; an actual
    # docker-save archive can be larger. This is NOT authority to create it.
    plausible=(logical*2+MIN_REMAINING_BYTES)<=free
    fp=hashlib.sha256(json.dumps(sorted(normalized),separators=(",",":")).encode()).hexdigest()
    return {
        "expected_live_roles_verified":len(normalized),
        "unique_images_present":len(seen),
        "image_service_baseline_fingerprint_sha256":fp,
        "logical_image_gib_ceiling":(logical+1024**3-1)//(1024**3),
        "free_gib_floor":free//1024**3,
        "conservative_local_image_retention_capacity":plausible,
        "image_archive_created":False,
        "isolated_image_recovery_rehearsed":False,
        "independent_offhost_image_custody":False,
        "previous_git_source_provenance_verified":False,
        "production_containers_or_volumes_modified":False,
        "safe_to_cutover":False,
    }


def main()->int:
    try:
        containers={}
        images={}
        for name in EXPECTED:
            item=json.loads(command(["docker","inspect","--format","{{json .}}",name]))
            label=(item.get("Config",{}).get("Labels") or {})
            image=item.get("Image")
            containers[name]={
                "running":item.get("State",{}).get("Running"),
                "image":image,
                "project":label.get("com.docker.compose.project"),
                "working_dir":label.get("com.docker.compose.project.working_dir"),
                "service":label.get("com.docker.compose.service"),
            }
            if isinstance(image,str) and image not in images:
                meta=json.loads(command(["docker","image","inspect","--format","{{json .}}",image]))
                if meta.get("Id")!=image:
                    raise ValueError("image source changed during inspection")
                images[image]=meta.get("Size")
        result=validate(containers,images,shutil.disk_usage(Path("/opt/kipnerter")).free)
        print(json.dumps(result,sort_keys=True))
        return 0 if result["conservative_local_image_retention_capacity"] else 3
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        print(json.dumps({"status":"NO_GO","reason_class":type(exc).__name__,
                          "image_archive_created":False,
                          "production_containers_or_volumes_modified":False,
                          "safe_to_cutover":False},sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
