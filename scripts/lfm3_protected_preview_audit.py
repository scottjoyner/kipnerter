#!/usr/bin/env python3
"""READ-ONLY live production audit for the password-protected LFM3 preview.

Uses the existing, private operator credential on the production host only.
Prints neither password, bcrypt hash, prompts, model response, nor auth headers.
"""
import base64
import hashlib
import json
import os
import pathlib
import pwd
import re
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path("/home/kipnerter/.local/state/lfm3-preview-20261105")
LIVE_CADDY = pathlib.Path("/opt/kipnerter/infra/caddy/Caddyfile")
LIVE_SHA = "6f24a5987968ac0ba12ca5895ee30e00744dd3bf4dd174c187432023606c255e"
OLD_SHA = "6713c86ef76caf2007f27f59482171efd082e2d6e8c023873748ea9ca523db68"
CADDY_IMAGE = "sha256:df7f1c2fb114453b951de51a98efc010db1655a92c2e86be6706714e2417a78d"
PREVIEW = "https://preview.kipnerter.com"


def hold(reason):
    print("LFM3_PROTECTED_PREVIEW_HOLD:", reason)
    raise SystemExit(3)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(base, path, *, secret=None, payload=None, timeout=15):
    headers = {}
    if secret is not None:
        headers["Authorization"] = "Basic " + base64.b64encode(
            ("beta:" + secret).encode("utf-8")
        ).decode("ascii")
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base + path, headers=headers, data=payload,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read(32769)
            if len(data) > 32768:
                hold("response exceeded bounded acceptance size")
            return response.status, data, response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        return error.code, error.read(1024), error.headers.get("Content-Type", "")


def main():
    if socket.gethostname() != "kipnerter-prod-01" or pwd.getpwuid(os.getuid()).pw_name != "kipnerter":
        hold("unexpected production host or operator principal")
    pwfile = ROOT / "preview.password"
    backup = ROOT / "Caddyfile.before"
    if not all(path.is_file() and not path.is_symlink() for path in
               (pwfile, backup, LIVE_CADDY, ROOT / "Caddyfile.candidate")):
        hold("missing guarded release material")
    if stat.S_IMODE(pwfile.stat().st_mode) != 0o600:
        hold("private operator password has unsafe permissions")
    if digest(backup) != OLD_SHA or digest(LIVE_CADDY) != LIVE_SHA:
        hold("deployed configuration or original rollback snapshot differs")
    if digest(ROOT / "Caddyfile.candidate") != LIVE_SHA:
        hold("deployed file does not match reviewed candidate")
    raw = LIVE_CADDY.read_text()
    for required in (
        "preview.kipnerter.com {", "basic_auth {", "beta $2",
        "reverse_proxy https://x1-370.tailcb8954.ts.net:8450",
        "header_up Host x1-370.tailcb8954.ts.net:8450",
    ):
        if required not in raw:
            hold("protected preview security configuration drift")
    password = pwfile.read_text().strip()
    if len(password) < 40:
        hold("insufficient operator password strength")
    try:
        container = json.loads(subprocess.check_output(
            ["docker", "inspect", "kipnerter-caddy-1"],
            timeout=8, stderr=subprocess.DEVNULL))[0]
        if not container["State"]["Running"] or container["Image"] != CADDY_IMAGE:
            hold("Caddy running image/container mismatch")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        hold("Caddy image identity cannot be attested")

    for path in ("/", "/chat", "/api/chat/completions",
                 "/_next/static/__nonexistent-lfm3.js"):
        status, _, _ = fetch(PREVIEW, path)
        if status != 401:
            hold("anonymous access did not fail closed for " + path)
    wrong, _, _ = fetch(PREVIEW, "/chat", secret=password + "-invalid")
    if wrong != 401:
        hold("incorrect password was accepted")

    code, page, _ = fetch(PREVIEW, "/chat", secret=password)
    if code != 200 or b"Message Kipnerter" not in page:
        hold("authenticated real Next.js chat unavailable")
    asset = re.search(rb'/_next/static/[^"\s<]+', page)
    if not asset:
        hold("real Next.js HTML did not reference a static asset")
    safe_asset = asset.group(0).decode("ascii").replace("&amp;", "&")
    code, data, mime = fetch(PREVIEW, safe_asset, secret=password)
    if code != 200 or not data or not any(t in mime for t in ("javascript", "css")):
        hold("authenticated browser asset did not load")

    payload = json.dumps({"messages": [{
        "role": "user", "content": "What is 2 + 2? Reply with the digit 4."
    }]}).encode("utf-8")
    start = time.monotonic()
    status, data, _ = fetch(
        PREVIEW, "/api/chat/completions", secret=password,
        payload=payload, timeout=35,
    )
    latency_ms = round((time.monotonic() - start) * 1000)
    response = json.loads(data) if status == 200 else {}
    result = response.get("reply")
    if (status != 200 or response.get("model") != "LFM3-1.7B" or
            not isinstance(result, str) or not re.search(r"\b4\b", result) or
            "SIMULATED DEMO RESPONSE" in result or "LOCAL HTTP FIXTURE" in result):
        hold("actual authenticated LFM3 generation failed acceptance")
    if latency_ms > 15000:
        hold("private preview canary exceeded 15-second latency gate")

    public_home, _, _ = fetch("https://kipnerter.com", "/")
    public_chat, _, _ = fetch("https://kipnerter.com", "/chat")
    api, _, _ = fetch("https://api.kipnerter.com", "/health/ready")
    if (public_home, public_chat, api) != (200, 404, 200):
        hold("public site routing unexpectedly changed")

    print("PROTECTED_PREVIEW_LIVE_PASS",
          "anonymous_routes_401=4", "wrong_password_401=true",
          "authenticated_chat_200=true", "static_asset_200=true",
          "real_model=LFM3-1.7B",
          "one_generation_latency_ms=" + str(latency_ms),
          "public_site_unchanged=true", "public_release=false")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        hold("read-only live acceptance failed")
