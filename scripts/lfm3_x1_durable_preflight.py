#!/usr/bin/env python3
"""Fail-closed, read-only prestart checks for the private x1-370 LFM3 stage.

Run as x1 user scott from systemd ExecStartPre. No downloads, shell eval,
service mutation, credentials, public listeners, or model changes.
"""
import hashlib
import json
import os
import pwd
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EXPECTED_MODEL = "3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4"
EXPECTED_BINARY = "3fd5de70af49313930b5df2e907fcf6dff795d0d64274d0c85369788a8b7f5bc"
EXPECTED_SOURCE = "c2a1dd2978ec7c7215e072bb62080ec2178e5a5b"
ROOT = Path("/home/scott/.local/share/kipnerter-lfm3-fast")
RUNTIME = ROOT / "runtime-vulkan-v0.7.0-3fd5de70/bin/llama-server"
MODEL = Path("/home/scott/models/LFM3-1.7B-Q4_K_M.gguf")
WEB = Path("/home/scott/git/kipnerter-lfm3-fast-stage-20261105")


def hold(reason):
    print("LFM3_DURABLE_HOLD: " + reason)
    raise SystemExit(3)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("model", "web"):
        hold("invalid preflight mode")
    role = sys.argv[1]
    if socket.gethostname() != "x1-370" or pwd.getpwuid(os.getuid()).pw_name != "scott":
        hold("wrong host or principal")

    model_port = os.environ.get("LFM3_MODEL_PORT")
    web_port = os.environ.get("LFM3_WEB_PORT")
    if (model_port, web_port) not in (("19181", "3357"), ("19182", "3358")):
        hold("ports must match the reviewed primary or canary pair")
    source = subprocess.run(
        ["git", "-C", str(WEB), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if source.returncode != 0 or source.stdout.strip() != EXPECTED_SOURCE:
        hold("web source checkout has unexpected commit")
    if not MODEL.is_file() or MODEL.stat().st_size != 1099627808:
        hold("official model file size mismatch")
    if not RUNTIME.is_file() or sha256(RUNTIME) != EXPECTED_BINARY:
        hold("pinned llama-server executable mismatch")

    if role == "model":
        if sha256(MODEL) != EXPECTED_MODEL:
            hold("official model SHA mismatch")
        # The 8-GiB admission minimum prevents new starts under pressure; a
        # running stage is never forcibly stopped by this check.
        available = next(
            (int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
             if line.startswith("MemAvailable:")), 0)
        if available < 8 * 1024 * 1024:
            hold("less than 8 GiB available RAM before model admission")
    else:
        endpoints = os.environ.get("KIPNERTER_LFM3_ENDPOINTS", "")
        try:
            parsed = json.loads(endpoints)
        except json.JSONDecodeError:
            hold("web endpoints are invalid JSON")
        expected = [{
            "name": "x1_fast_cpu",
            "baseUrl": "http://127.0.0.1:" + model_port,
            "model": "lfm3-1.7b-x1-fast",
            "adapter": "openai",
            "role": "interactive",
            "maxInflight": 1,
            "maxOutputTokens": 128,
        }]
        if parsed != expected:
            hold("web endpoints differ from single reviewed private model")
        # Type=simple reports the model service started before it is ready;
        # allow a bounded cold-start health window without extra generation.
        ready = False
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:" + model_port + "/health", timeout=2
                ) as response:
                    if response.status == 200:
                        ready = True
                        break
            except (OSError, urllib.error.HTTPError, ValueError):
                pass
            time.sleep(1)
        if not ready:
            hold("model health unavailable after bounded 30-second startup")

    print("LFM3_DURABLE_PREFLIGHT_PASS role=" + role)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        hold("preflight not completed")
