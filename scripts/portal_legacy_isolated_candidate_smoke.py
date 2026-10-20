#!/usr/bin/env python3
"""Ephemeral, research-only API image launch rehearsal: no production access.

Proves isolation harness behavior for a *different*, cached API candidate,
NOT runnable rollback of missing historical web/API OCI identities.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import time

RESEARCH = {
    "compat-031": "sha256:321f8eea80e45afeb34d15e645cfc1277361b5baf7e66ab45d2d99ebb3fb2197",
    "synthetic-loopback": "sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f",
}
TOKEN = "1" * 40  # visibly synthetic source/release identity, no secret.
SYNTHETIC_HMAC = "SYNTHETIC_ONLY_NEVER_PRODUCTION_" + "a" * 48
SYNTHETIC_BEARER = "SYNTHETIC_ONLY_NEVER_PRODUCTION_" + "b" * 48
PRIVATE_ROUTES = ("/api/v1/control-plane/overview",
                  "/api/v1/control-plane/nodes")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
FIXTURE_SERVER = r"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
class SyntheticHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/health", "/ready", "/api/v1", "/api/v1/release"):
            code = 200
        elif (self.path in ("/api/v1/control-plane/overview",
                            "/api/v1/control-plane/nodes") and
              self.headers.get("Authorization") ==
                  "Bearer " + os.environ["KIPNERTER_GATEWAY_BEARER_TOKEN"]):
            code = 200
        else:
            code = 401
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")
    def log_message(self, *args):
        return
HTTPServer(("127.0.0.1", 8080), SyntheticHandler).serve_forever()
"""
PROBE = r"""
import json, os, urllib.error, urllib.request
results = {}
for path in ("/health", "/ready", "/api/v1", "/api/v1/release",
             "/api/v1/control-plane/overview", "/api/v1/control-plane/nodes",
             "/api/v1/gateway/lmstudio/v1/models"):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080" + path,
                                    timeout=2) as response:
            results[path] = response.status
    except urllib.error.HTTPError as e:
        results[path] = e.code
    except Exception:
        results[path] = 0
for path in ("/api/v1/control-plane/overview", "/api/v1/control-plane/nodes"):
    req = urllib.request.Request(
        "http://127.0.0.1:8080" + path,
        headers={"Authorization": "Bearer " +
                 os.environ["KIPNERTER_GATEWAY_BEARER_TOKEN"]})
    key = path + ":synthetic-auth"
    try:
        with urllib.request.urlopen(req, timeout=2) as response:
            results[key] = response.status
    except urllib.error.HTTPError as e:
        results[key] = e.code
    except Exception:
        results[key] = 0
print(json.dumps(results, separators=(",", ":"), sort_keys=True))
"""
EXPECTED = {
    "/health": 200, "/ready": 200, "/api/v1": 200, "/api/v1/release": 200,
    "/api/v1/control-plane/overview": 401,
    "/api/v1/control-plane/nodes": 401,
    "/api/v1/gateway/lmstudio/v1/models": 401,
    "/api/v1/control-plane/overview:synthetic-auth": 200,
    "/api/v1/control-plane/nodes:synthetic-auth": 200,
}


def runner(args, *, timeout=25):
    if any(not isinstance(v, str) for v in args):
        raise ValueError("invalid Docker call")
    result = subprocess.run(args, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, check=False,
                            timeout=timeout)
    if result.returncode:
        raise ValueError("isolated container action did not succeed")
    if len(result.stdout) > 4096:
        raise ValueError("unbounded Docker metadata response")
    return result.stdout.decode("ascii", "strict").strip()


def commands(name: str, image: str, *, synthetic: bool = False):
    if not re.fullmatch(r"kp-legacy-isolated-[a-f0-9]{12}", name):
        raise ValueError("unapproved disposable container name")
    if image not in RESEARCH.values() or not DIGEST.fullmatch(image):
        raise ValueError("unapproved immutable research image")
    start = [
        "docker", "run", "--detach", "--rm", "--pull", "never",
        "--name", name,
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "64", "--memory", "384m", "--cpus", "0.5",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=33554432",
        "--tmpfs", "/run:rw,nosuid,nodev,noexec,size=8388608",
        "--tmpfs", "/data:rw,nosuid,nodev,noexec,size=33554432",
        "--env", "KIPNERTER_ENV=research",
        "--env", "KIPNERTER_RELEASE_SHA=" + TOKEN,
        "--env", "KIPNERTER_LOCATION_HMAC_SECRET=" + SYNTHETIC_HMAC,
        "--env", "KIPNERTER_GATEWAY_BEARER_TOKEN=" + SYNTHETIC_BEARER,
        "--restart", "no",
        image,
    ]
    if synthetic:
        if image != RESEARCH["synthetic-loopback"]:
            raise ValueError("synthetic server image not pinned to fixture")
        start += ["python3", "-u", "-c", FIXTURE_SERVER]
    check = [
        "docker", "inspect", "--format",
        '{{.HostConfig.NetworkMode}}|{{.HostConfig.ReadonlyRootfs}}|'
        '{{len .HostConfig.PortBindings}}|{{.Image}}|'
        '{{.State.Running}}|{{len .Mounts}}|{{len .HostConfig.Tmpfs}}|'
        '{{json .HostConfig.Tmpfs}}|{{.HostConfig.Memory}}|'
        '{{.HostConfig.PidsLimit}}|{{.HostConfig.NanoCpus}}|'
        '{{json .HostConfig.CapDrop}}|{{json .HostConfig.SecurityOpt}}|'
        '{{.HostConfig.AutoRemove}}',
        name,
    ]
    probe = ["docker", "exec", name, "python3", "-c", PROBE]
    remove = ["docker", "rm", "--force", name]
    return start, check, probe, remove


def safety_inspect(line: str, image: str):
    parts = line.split("|")
    expected = ["none", "true", "0", image, "true", "0", "3"]
    if len(parts) != 14 or parts[:7] != expected:
        raise ValueError("container isolated-network/no-mount receipt mismatch")
    expected_tmpfs = {
        "/tmp": "rw,nosuid,nodev,noexec,size=33554432",
        "/run": "rw,nosuid,nodev,noexec,size=8388608",
        "/data": "rw,nosuid,nodev,noexec,size=33554432",
    }
    if (json.loads(parts[7]) != expected_tmpfs
            or parts[8:11] != ["402653184", "64", "500000000"]
            or json.loads(parts[11]) != ["ALL"]
            or json.loads(parts[12]) != ["no-new-privileges"]
            or parts[13] != "true"):
        raise ValueError("isolated candidate resource or security policy changed")


def classify_probe(response: str):
    if len(response) > 2048:
        raise ValueError("unbounded private candidate response")
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("duplicate probe receipt")
            result[name] = value
        return result
    actual = json.loads(response, object_pairs_hook=unique)
    if (not isinstance(actual, dict) or set(actual) != set(EXPECTED)
            or any(type(actual[key]) is not int or actual[key] != wanted
                   for key, wanted in EXPECTED.items())):
        raise ValueError("isolated candidate response did not match contract")
    return True


def rehearsal(role: str, *, call=runner, pauses=time.sleep, nonce=None):
    if role not in RESEARCH:
        raise ValueError("research-only image role rejected")
    image = RESEARCH[role]
    name = "kp-legacy-isolated-" + (nonce or secrets.token_hex(6))
    start, inspect, probe, remove = commands(
        name, image, synthetic=role == "synthetic-loopback")
    # Prequalify exact pin using the local existing cache: never a mutable tag.
    found = call(["docker", "image", "inspect", "--format", "{{.Id}}", image])
    if found != image:
        raise ValueError("exact image not cached at original pin")
    attempted = False
    success = False
    cleanup_ok = False
    try:
        # Mark before daemon starts: a timeout may have created the container.
        attempted = True
        container = call(start, timeout=30)
        if not re.fullmatch(r"[a-f0-9]{64}", container):
            raise ValueError("untrusted disposable container ID")
        safety_inspect(call(inspect, timeout=8), image)
        for attempt in range(18):
            try:
                classify_probe(call(probe, timeout=10))
                success = True
                break
            except (ValueError, subprocess.SubprocessError):
                if attempt != 17:
                    pauses(.35)
        if not success:
            raise ValueError("isolated compatibility probe failed")
    finally:
        if attempted:
            try:
                call(remove, timeout=15)
                leftovers = call(
                    ["docker", "ps", "--all", "--filter", "name=^/" + name + "$",
                     "--format", "{{.Names}}"],
                    timeout=8)
                cleanup_ok = not leftovers
                if not cleanup_ok:
                    raise ValueError("disposable container still present")
            except (ValueError, subprocess.SubprocessError):
                cleanup_ok = False
    if not cleanup_ok:
        raise ValueError("disposable container cleanup not verified")
    return {
        "status": ("SYNTHETIC_LOOPBACK_ISOLATION_PASS_NOT_LEGACY"
                   if role == "synthetic-loopback" else
                   "RESEARCH_API_ISOLATION_PASS_NOT_LEGACY"),
        "research_image_used": True,
        "synthetic_http_fixture": role == "synthetic-loopback",
        "actual_candidate_api_health_verified": role == "compat-031" and success,
        "isolated_readonly_network_none": True,
        "synthetic_release_identity": True,
        "http_health_and_deny_checks_passed": success,
        "synthetic_authenticated_control_plane_checks_passed": success,
        "disposable_container_cleanup_verified": cleanup_ok,
        "original_legacy_oci_images_recovered": False,
        "original_legacy_api_equivalence_verified": False,
        "legacy_web_image_rehearsed": False,
        "production_auth_or_database_access": False,
        "production_modified": False,
        "runnable_original_rollback_verified": False,
        "independent_custody_verified": False,
        "safe_to_cutover": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-role", choices=tuple(RESEARCH), required=True)
    opts = parser.parse_args()
    try:
        report = rehearsal(opts.research_role)
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        report = {
            "status": "HOLD", "original_legacy_oci_images_recovered": False,
            "runnable_original_rollback_verified": False,
            "safe_to_cutover": False,
        }
        print(json.dumps(report, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
