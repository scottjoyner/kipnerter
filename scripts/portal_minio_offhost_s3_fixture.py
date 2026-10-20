#!/usr/bin/env python3
"""Run synthetic no-network S3 parity on Destroyer with cached, pinned MinIO.

No production mounts, persistent state or public endpoints. Positive result is
NEVER a real backup restoration, immutable production image or release approval.
"""
import json
import shlex
import secrets
import subprocess
from pathlib import Path

HOST = "destroyer"
REMOTE_CODE = (Path(__file__).resolve().parent / "portal_minio_disposable_remote.py").read_text(encoding="utf-8")

def verify_response(result, challenge):
    if not isinstance(result, dict) or result.get("challenge") != challenge:
        raise ValueError("missing remote challenge agreement")
    for field in ("host_ports_published", "host_mounts_attached",
                  "production_data_accessed","real_backup_restored",
                  "minio_prod_image_identity_verified",
                  "independent_custody_verified","production_recovery_approved"):
        if result.get(field) is not False:
            raise ValueError("unsafe synthetic-only report claim: " + field)
    if result.get("network_external") != "none":
        raise ValueError("network isolation unverified")
    if result.get("cleanup_verified") is not True:
        raise ValueError("remote scratch cleanup unverified")
    if result.get("status") == "SYNTHETIC_ONLY_PASS":
        for field in ("server_cached_id_verified", "mc_cached_id_verified",
                      "synthetic_object_source_verified",
                      "synthetic_object_copy_verified",
                      "negative_integrity_control_rejected",
                      "sha256_matched_on_both_isolated_servers"):
            if result.get(field) is not True:
                raise ValueError("incomplete synthetic parity witness: " + field)
        size=result.get("object_byte_count")
        if type(size) is not int or not 1000 <= size <= 1300:
            raise ValueError("invalid synthetic object size")
    elif result.get("status") != "HOLD":
        raise ValueError("invalid synthetic witness status")
    return result

def probe(*, runner=subprocess.run, host=HOST):
    if host != HOST:
        raise ValueError("fixed prequalified synthetic host required")
    challenge=secrets.token_hex(32)
    request=json.dumps({"challenge":challenge},sort_keys=True,separators=(",",":")).encode()
    remote="python3 -c "+shlex.quote(REMOTE_CODE)
    command=["ssh","-T","-o","BatchMode=yes",
             "-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=6",
             "-o","ClearAllForwardings=yes","-o","RequestTTY=no",
             "--",HOST,remote]
    response=runner(command,input=request,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,check=False,timeout=130)
    if response.returncode or not 2 <= len(response.stdout) <= 4096:
        raise ValueError("no bounded SSH synthetic S3 witness response")
    try:
        result=json.loads(response.stdout)
    except (TypeError,UnicodeError,ValueError):
        raise ValueError("invalid JSON from synthetic S3 witness") from None
    return verify_response(result,challenge)

if __name__=="__main__":
    try:
        report=probe()
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print(json.dumps({"status":"HOLD","reason_class":type(exc).__name__,
                          "production_recovery_approved":False}))
        raise SystemExit(2)
    print(json.dumps(report,sort_keys=True))
    raise SystemExit(0 if report["status"]=="SYNTHETIC_ONLY_PASS" else 2)
