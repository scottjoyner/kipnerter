#!/usr/bin/env python3
"""READ-ONLY audit of the dedicated, local-only x1-370 LFM3 + Next.js stage.

No model or service loading; no Docker, firewall, SSH, or credential changes.
Makes exactly one bounded actual LFM3 completion request and logs no reply text.
"""
import hashlib
import json
import os
import pwd
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MODEL_FILE = Path("/home/scott/models/LFM3-1.7B-Q4_K_M.gguf")
WEB_CHECKOUT = Path("/home/scott/git/kipnerter-lfm3-fast-stage-20261105")
EXPECTED_MODEL_SHA = "3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4"
EXPECTED_SOURCE_SHA = "c2a1dd2978ec7c7215e072bb62080ec2178e5a5b"
MODEL_NAME = "lfm3-1.7b-x1-fast"
MODEL_URL = "http://127.0.0.1:19181"
WEB_URL = "http://127.0.0.1:3357"
UNITS = {
    "model": ("kipnerter-lfm3-fast-model.service", 2500 * 1024 * 1024, "6s", 80),
    "web": ("kipnerter-lfm3-fast-web.service", 384 * 1024 * 1024, "750ms", 110),
}
PINNED_RUNTIME = Path("/home/scott/.local/share/kipnerter-lfm3-fast/runtime-vulkan-v0.7.0-3fd5de70")
RUNTIME_BINARY_SHA = "3fd5de70af49313930b5df2e907fcf6dff795d0d64274d0c85369788a8b7f5bc"



def hold(reason):
    print("X1_FAST_STAGE_HOLD:", reason)
    raise SystemExit(3)


def capture(argv, timeout=10, env=None):
    try:
        return subprocess.check_output(argv, text=True, timeout=timeout, stderr=subprocess.DEVNULL, env=env).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        hold("required read-only command unavailable")


def small_json(url, *, request=None, timeout=5):
    with urllib.request.urlopen(request or url, timeout=timeout) as response:
        raw = response.read(32769)
        if len(raw) > 32768 or response.status != 200:
            hold("unexpected HTTP status or oversized response")
        return json.loads(raw)


def validate_local_bindings():
    ports = {"19181", "3357"}
    present = set()
    for line in capture(["ss", "-ltnH"], 6).splitlines():
        cols = line.split()
        if len(cols) < 5:
            continue
        local = cols[3]
        for port in ports:
            if local.endswith(":" + port):
                if local != "127.0.0.1:" + port:
                    hold("stage port is not exclusively IPv4 loopback")
                present.add(port)
    if present != ports:
        hold("stage port is missing")
    if any(":" + p in capture(["ss", "-ltnH"], 6) for p in ("19182", "3358")):
        hold("old temporary canary port is still listening")


def audit_systemd_units():
    env = os.environ.copy()
    env.update(HOME="/home/scott", XDG_RUNTIME_DIR="/run/user/1000",
               DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1000/bus")
    for role, (unit, memory_cap, quota, tasks) in UNITS.items():
        output = capture(
            ["systemctl", "--user", "show", unit,
             "-p", "ActiveState", "-p", "MemoryMax", "-p", "MemoryCurrent",
             "-p", "MemorySwapCurrent", "-p", "CPUQuotaPerSecUSec",
             "-p", "TasksMax", "-p", "ExecStart", "-p", "Restart",
             "-p", "FragmentPath", "-p", "NoNewPrivileges",
             "-p", "PrivateTmp", "-p", "ProtectSystem"],
            8, env=env,
        )
        data = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        if data.get("ActiveState") != "active":
            hold("fast stage service is not active")
        if data.get("Restart") != "on-failure":
            hold("durable service must restart on failure")
        if data.get("FragmentPath") != f"/home/scott/.config/systemd/user/{unit}":
            hold("unit must be a persistent operator-managed service")
        if data.get("NoNewPrivileges") != "yes" or data.get("PrivateTmp") != "yes" or data.get("ProtectSystem") != "full":
            hold("verified user-systemd sandbox policy is missing")
        enabled = capture(["systemctl", "--user", "is-enabled", unit], 5, env=env)
        if enabled != "enabled":
            hold("durable unit is not enabled for login boot")
        if int(data.get("MemoryMax", "0")) > memory_cap or int(data.get("MemoryMax", "0")) <= 0:
            hold("memory quota exceeds reviewed bound")
        if int(data.get("MemoryCurrent", "0")) > memory_cap:
            hold("service exceeds memory cap")
        if int(data.get("MemorySwapCurrent", "-1")) != 0:
            hold("service used swap")
        if data.get("CPUQuotaPerSecUSec") != quota or int(data.get("TasksMax", "0")) > tasks:
            hold("CPU/task limits changed")
        cmd = data.get("ExecStart", "")
        if role == "model" and (MODEL_NAME not in cmd or str(MODEL_FILE) not in cmd or
                                str(PINNED_RUNTIME / "bin/llama-server") not in cmd):
            hold("model service identity changed")
        if role == "web" and ("127.0.0.1" not in cmd or "LFM3_WEB_PORT" not in cmd):
            hold("frontend binding changed")
        print(f"unit={role} active=true memory_current_bytes={data['MemoryCurrent']} "
              f"memory_cap_bytes={data['MemoryMax']} memory_swap_bytes=0")


def main():
    if socket.gethostname() != "x1-370" or pwd.getpwuid(os.getuid()).pw_name != "scott":
        hold("unexpected machine or principal")
    source = capture(["git", "-C", str(WEB_CHECKOUT), "rev-parse", "HEAD"], 8)
    if source != EXPECTED_SOURCE_SHA:
        hold("frontend checkout is not the independently reviewed exact head")
    if not MODEL_FILE.is_file() or MODEL_FILE.stat().st_size != 1099627808:
        hold("official GGUF absent or size mismatch")
    digest = hashlib.sha256()
    with MODEL_FILE.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != EXPECTED_MODEL_SHA:
        hold("official GGUF checksum mismatch")

    if not (PINNED_RUNTIME / "bin/llama-server").is_file():
        hold("reboot-safe pinned runtime is missing")
    if hashlib.sha256((PINNED_RUNTIME / "bin/llama-server").read_bytes()).hexdigest() != RUNTIME_BINARY_SHA:
        hold("reboot-safe pinned runtime executable hash mismatch")
    runtime_manifest = subprocess.run(
        ["sha256sum", "-c", "RUNTIME_SHA256SUMS.txt"],
        cwd=PINNED_RUNTIME, capture_output=True, text=True, timeout=15, check=False)
    if runtime_manifest.returncode != 0:
        hold("pinned llama runtime library checksums did not verify")
    linger = capture(["loginctl", "show-user", "scott", "-p", "Linger", "--value"], 5)
    if linger != "yes":
        hold("user-systemd is not configured to start without login")
    validate_local_bindings()
    audit_systemd_units()
    available = int(next(
        line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemAvailable:")
    ))
    if available < 8 * 1024 * 1024:
        hold("host has less than 8 GiB available RAM")

    catalog = small_json(MODEL_URL + "/v1/models")
    if [m.get("id") for m in catalog.get("data", [])] != [MODEL_NAME]:
        hold("resident fast model identity mismatch")
    start = time.monotonic()
    with urllib.request.urlopen(WEB_URL + "/chat", timeout=8) as page:
        if page.status != 200 or b"Message Kipnerter" not in page.read(250000):
            hold("real chat UI unavailable")
    web_ms = round((time.monotonic() - start) * 1000)

    payload = json.dumps({"messages": [
        {"role": "user", "content": "What is 2 + 2? Reply with the digit 4."}
    ]}).encode()
    request = urllib.request.Request(
        WEB_URL + "/api/chat/completions", data=payload, method="POST",
        headers={"Content-Type": "application/json"})
    started = time.monotonic()
    answer = small_json(WEB_URL, request=request, timeout=45)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    reply = answer.get("reply")
    if (answer.get("model") != "LFM3-1.7B" or not isinstance(reply, str)
            or not re.search(r"\b4\b", reply)
            or "SIMULATED DEMO RESPONSE" in reply or "LOCAL HTTP FIXTURE" in reply):
        hold("actual model output did not meet acceptance contract")
    if elapsed_ms > 15000:
        hold("single-request fast-stage latency exceeded 15-second canary gate")

    print(f"LIVE_X1_FAST_STAGE_PASS web_get_ms={web_ms} "
          f"single_generation_latency_ms={elapsed_ms} sample_count=1 "
          "exact_source=true official_model_sha_verified=true "
          "web_and_model_loopback_only=true durable_units_enabled=true public_cutover=false")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, urllib.error.HTTPError, urllib.error.URLError):
        hold("live audit failed")
