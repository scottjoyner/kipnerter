#!/usr/bin/env python3
"""Read-only source-reference classification for TWO live legacy app containers.

Never prints image names, registry URLs, container Config.Env, API credentials,
Dockerfile source, or local private paths. Does not pull, build, commit, export,
save or stop anything. SHA fingerprints describe references but are NOT
attestations that the original image layers can be restored.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess

SERVICES=(
    ("gateway", "kipnerter-api-1", "apps/api/Dockerfile"),
    ("web", "kipnerter-web-1", "apps/web/Dockerfile"),
)
SHA64=re.compile(r"[a-f0-9]{64}\Z")
DIGEST_REF=re.compile(r"[^\s:@]+(?:/[^\s:@]+)*@sha256:[a-f0-9]{64}\Z")
ID_REF=re.compile(r"sha256:[a-f0-9]{64}\Z")
TAG_REF=re.compile(r"[a-zA-Z0-9_./-]+:[a-zA-Z0-9_.-]+\Z")
UNTAGGED=re.compile(r"[a-zA-Z0-9_./-]+\Z")


def classify_ref(value: str)->str:
    if not isinstance(value,str) or len(value)>300:
        raise ValueError("invalid source reference")
    if ID_REF.fullmatch(value):
        return "local_image_id"
    if DIGEST_REF.fullmatch(value):
        return "registry_immutable_digest"
    if TAG_REF.fullmatch(value):
        return "mutable_registry_or_local_tag"
    if UNTAGGED.fullmatch(value):
        return "default_tag_or_local_build"
    raise ValueError("untrusted reference syntax")


def classify(role: str, configured_ref: str, runtime_id: str,
             compose_label: str, cache_exists: bool, dockerfile_hash: str)->dict:
    if (role not in ("gateway","web") or
            not ID_REF.fullmatch(runtime_id) or
            type(cache_exists) is not bool or
            not SHA64.fullmatch(dockerfile_hash) or
            not isinstance(compose_label,str) or len(compose_label)>200):
        raise ValueError("untrusted old-app source identity")
    kind=classify_ref(configured_ref)
    return {
        "role":role,
        "original_configured_image_ref_kind":kind,
        "configured_ref_sha256":hashlib.sha256(configured_ref.encode()).hexdigest(),
        "live_immutable_image_id_sha256":
            hashlib.sha256(runtime_id.encode()).hexdigest(),
        "compose_config_hash_label_present":bool(compose_label.strip()),
        "legacy_dockerfile_sha256":dockerfile_hash,
        "running_image_available_for_docker_save":cache_exists,
        "source_matches_running_image_layers_proven":False,
        "registry_artifact_recovered_and_verified":False,
        "production_modified":False,
        "safe_to_cutover":False,
    }


def checked(cmd: list[str], timeout:int=10)->str:
    proc=subprocess.run(cmd,capture_output=True,text=True,check=True,timeout=timeout)
    if len(proc.stdout)>1000:
        raise ValueError("unbounded Docker source metadata")
    return proc.stdout.strip()


def main()->int:
    try:
        results=[]
        for role,container,source_name in SERVICES:
            # Explicit projected fields only. No Docker environment or mounts.
            line=checked(["docker","inspect","--format",
                '{{.Config.Image}}|{{.Image}}|'
                '{{index .Config.Labels "com.docker.compose.config-hash"}}',
                container])
            fields=line.split("|")
            if len(fields)!=3:
                raise ValueError("invalid legacy container source fields")
            reference,identity,config_hash=fields
            dockerfile=Path("/opt/kipnerter")/source_name
            if (dockerfile.is_symlink() or not dockerfile.is_file() or
                    dockerfile.stat().st_size>256000):
                raise ValueError("source Dockerfile unavailable or untrusted")
            digest=hashlib.sha256(dockerfile.read_bytes()).hexdigest()
            try:
                # No network, image pull, or local daemon changes.
                checked(["docker","image","inspect","--format","{{.Id}}",
                         identity],timeout=10)
                cached=True
            except subprocess.CalledProcessError:
                cached=False
            results.append(classify(role,reference,identity,config_hash,cached,digest))
        print(json.dumps({
            "legacy_app_image_sources":results,
            "old_app_images_runnable_from_cache":all(
                row["running_image_available_for_docker_save"] for row in results),
            "production_files_or_containers_modified":False,
            "safe_to_cutover":False,
        },sort_keys=True))
        # Expected HOLD when production had both app images pruned.
        return 0 if all(row["running_image_available_for_docker_save"] for row in results) else 3
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError) as error:
        print(json.dumps({"status":"NO_GO","reason_class":type(error).__name__,
                          "production_files_or_containers_modified":False,
                          "safe_to_cutover":False},sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
