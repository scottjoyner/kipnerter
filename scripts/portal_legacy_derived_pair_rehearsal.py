#!/usr/bin/env python3
"""Research-only historical WEB + API fail/restart rehearsal on a Docker worker.

These are source-DERIVED builds, not the missing original production OCI images.
Never contacts production, publishes ports or attaches host/production volumes.
Fails closed if the cached image identities, isolation or cleanup deviate.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
import time

DEFAULT_IDS = {
    "api": "sha256:fa35913ecb97e376ae1de29ae1d100d8e830559b43364d3e97342d8fd43e0d9c",
    "web": "sha256:ff072bff623892b71492b1388eb212e66f6a1e8ae1d5f1d1c6983171882f781f",
}
HARDENED_WEB_ID = "sha256:3d6cc7837f1d5a8032b0eae71876d3784d50162691789dfb8d22a9d0f57958b2"
ALLOWED_ROLE_IDS = {"api": {DEFAULT_IDS["api"]},
                    "web": {DEFAULT_IDS["web"], HARDENED_WEB_ID}}
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
CID = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"kp-derived-legacy-(?:api|web)-[0-9a-f]{16}-(?:initial|relaunched)\Z")

API_CHECK = '''
import urllib.request,urllib.error
for path,want in (("/health",200),("/ready",200),("/api/v1",200),
                  ("/api/v1/services",200),("/api/v1/models",200),
                  ("/api/v1/release",404),("/api/v1/control-plane/overview",404)):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000"+path,timeout=2) as res:
            actual=res.status
    except urllib.error.HTTPError as exc:
        actual=exc.code
    assert actual==want,(path,actual)
'''
WEB_CHECK = '''
(async()=>{
  for(const [path,want] of [["/",200],["/chat",404]]){
    const r=await fetch("http://127.0.0.1:3000"+path,
      {signal:AbortSignal.timeout(1800)});
    if(r.status!==want)process.exit(2);
    if(path==="/"&&!(await r.text()).includes("Your AI systems, available anywhere."))
       process.exit(3);
  }
})().catch(()=>process.exit(4));
'''

def docker(argv: list[str], *, timeout=18) -> str:
    try:
        p = subprocess.run(["docker", *argv], capture_output=True,
                           text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("bounded Docker operation failed") from exc
    if p.returncode != 0:
        # Do not propagate stdout/stderr (can contain sensitive metadata).
        raise ValueError("bounded Docker operation failed")
    if len(p.stdout) > 2_000_000:
        raise ValueError("Docker metadata exceeded bound")
    return p.stdout.strip()

def pin_image(image_id: str) -> None:
    if not isinstance(image_id, str) or not IMAGE_ID.fullmatch(image_id):
        raise ValueError("immutable research image id required")
    result = docker(["image", "inspect", image_id, "--format", "{{.Id}}"], timeout=9)
    if result != image_id:
        raise ValueError("local immutable research image absent or changed")

def validate_container(meta: dict, *, image_id: str, name: str, user: str) -> None:
    if not isinstance(meta, dict) or not CID.fullmatch(str(meta.get("Id", ""))):
        raise ValueError("unknown container identity")
    cfg = meta.get("Config")
    host = meta.get("HostConfig")
    state = meta.get("State")
    if not all(isinstance(x, dict) for x in (cfg, host, state)):
        raise ValueError("missing effective Docker isolation readback")
    if (meta.get("Name") != "/" + name or
            meta.get("Image") != image_id or cfg.get("Image") != image_id or
            cfg.get("User") != user or state.get("Running") is not True):
        raise ValueError("research container identity mismatch")
    if (host.get("NetworkMode") != "none" or
            host.get("ReadonlyRootfs") is not True or
            host.get("Privileged") is not False or
            host.get("CapDrop") != ["ALL"] or
            host.get("PortBindings") not in ({}, None) or
            host.get("Binds") not in ([], None) or
            host.get("VolumesFrom") not in ([], None) or
            meta.get("Mounts") != [] or
            host.get("PidsLimit") != 96 or
            host.get("RestartPolicy", {}).get("Name") not in ("", "no")):
        raise ValueError("unexpected privileged, mounted or reachable container")
    if cfg.get("Volumes") not in ({}, None):
        raise ValueError("image auto-mount volume would violate isolation")
    if (host.get("SecurityOpt") is None or
            "no-new-privileges" not in host["SecurityOpt"] or
            not isinstance(host.get("Memory"), int) or host["Memory"] > 805306368 or
            host["Memory"] <= 0):
        raise ValueError("missing resource and privilege control")
    tmpfs = host.get("Tmpfs")
    if not isinstance(tmpfs, dict) or set(tmpfs) != {"/tmp"}:
        raise ValueError("unexpected tmpfs or implicit persistent write")
    if "nosuid" not in tmpfs["/tmp"] or "size=33554432" not in tmpfs["/tmp"]:
        raise ValueError("unbounded tmpfs")
    # Never disclose cfg.Env in logs or reports.

def start(role: str, image_id: str, name: str, owned: set[str]) -> str:
    if (role not in ("api", "web") or not NAME.fullmatch(name) or
            not name.startswith("kp-derived-legacy-" + role + "-") or
            image_id not in ALLOWED_ROLE_IDS[role]):
        raise ValueError("invalid bounded research identity")
    user = "65532:65532" if role == "api" else "10001:10001"
    size = "512m" if role == "api" else "768m"
    result = docker([
        "run", "-d", "--rm", "--name", name, "--network", "none",
        "--read-only", "--user", user, "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "96",
        "--memory", size, "--cpus", "1",
        "--tmpfs", "/tmp:rw,nosuid,size=33554432",
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "NODE_ENV=production",
        "-e", "NEXT_TELEMETRY_DISABLED=1", image_id
    ], timeout=24)
    if not CID.fullmatch(result):
        raise ValueError("unexpected Docker create acknowledgement")
    owned.add(result)  # Record ownership before any subsequent fallible check.
    raw = docker(["inspect", result, "--format", "{{json .}}"], timeout=8)
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Docker readback invalid") from exc
    validate_container(meta, image_id=image_id, name=name, user=user)
    return result

def qualify(role: str, cid: str) -> None:
    if not CID.fullmatch(cid):
        raise ValueError("invalid disposable container id")
    command = ["python", "-B", "-c", API_CHECK] if role == "api" else [
        "node", "-e", WEB_CHECK
    ]
    for attempt in range(35):
        try:
            docker(["exec", cid, *command], timeout=8)
            return
        except ValueError:
            if attempt >= 34:
                raise ValueError("historical service not healthy or routes differ")
            time.sleep(0.25)
    raise ValueError("startup did not qualify")

def gone(cid: str) -> bool:
    if not CID.fullmatch(cid):
        raise ValueError("invalid container id for removal")
    p = subprocess.run(["docker", "inspect", cid, "--format", "{{.Id}}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=6, check=False)
    return p.returncode != 0

def remove_owned(owned: set[str], *, sigkill: bool) -> None:
    for cid in sorted(owned):
        if not CID.fullmatch(cid):
            raise ValueError("refusing cleanup with unknown container id")
        if not gone(cid):
            if sigkill:
                docker(["kill", "--signal", "SIGKILL", cid], timeout=9)
            else:
                docker(["rm", "-f", cid], timeout=9)
        for attempt in range(20):
            if gone(cid):
                break
            time.sleep(0.2)
        else:
            raise ValueError("research cleanup not proven")
    owned.clear()

def rehearse(api_id: str, web_id: str) -> dict:
    if api_id == web_id:
        raise ValueError("historical API and web must have different exact images")
    pin_image(api_id)
    pin_image(web_id)
    owned: set[str] = set()
    nonce = secrets.token_hex(8)
    report = {
        "status": "HOLD", "historical_source_revision": "05955fef99cb",
        "historical_original_oci_images_recovered": False,
        "derived_dependency_reproducibility_verified": False,
        "web_npm_security_review_passed": False,
        "hardened_web_npm_audit_at_research_build_passed": web_id == HARDENED_WEB_ID,
        "cross_version_portal_auth_route_parity_verified": False,
        "independent_custody_verified": False, "production_modified": False,
        "safe_to_cutover": False,
    }
    complete = False
    try:
        for step in ("initial", "relaunched"):
            a_name = "kp-derived-legacy-api-" + nonce + "-" + step
            w_name = "kp-derived-legacy-web-" + nonce + "-" + step
            a = start("api", api_id, a_name, owned)
            w = start("web", web_id, w_name, owned)
            qualify("api", a)
            qualify("web", w)
            # Only the two exact generated disposable containers are SIGKILLed.
            remove_owned(owned, sigkill=True)
        complete = True
    finally:
        try:
            remove_owned(owned, sigkill=False)
        except (ValueError, OSError, subprocess.SubprocessError):
            complete = False
            report["cleanup_verified"] = False
        else:
            report["cleanup_verified"] = True
    if complete:
        report["status"] = "SOURCE_DERIVED_PAIR_RESTART_PASS_NOT_PRODUCTION_ROLLBACK"
        report["restarts_verified"] = 2
        report["historical_web_root_200"] = True
        report["historical_api_health_200"] = True
        report["historical_web_chat_404_expected"] = True
        report["historical_api_control_plane_404_expected"] = True
        report["network_none_and_no_mounts_verified"] = True
    return report

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-only", action="store_true", required=True)
    parser.add_argument("--api-image-id", default=DEFAULT_IDS["api"])
    parser.add_argument("--web-image-id", default=DEFAULT_IDS["web"])
    args = parser.parse_args()
    try:
        result = rehearse(args.api_image_id, args.web_image_id)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        result = {"status": "HOLD", "reason_class": type(exc).__name__,
                  "cleanup_verified": False, "safe_to_cutover": False,
                  "production_modified": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"].startswith("SOURCE_DERIVED_PAIR_RESTART_PASS") else 2

if __name__ == "__main__":
    sys.exit(main())
