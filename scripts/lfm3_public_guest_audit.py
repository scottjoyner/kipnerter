#!/usr/bin/env python3
"""READ-ONLY proof of the bounded, anonymous LFM3 chat guest release.

Runs as kipnerter on the production host. No Docker mutations, config writes,
credentials, HTTP access logs, or response body/secret logging.
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

ROOT = Path("/home/kipnerter/.local/state/lfm3-public-edge-gate-20261105")
CADDY = Path("/opt/kipnerter/infra/caddy/Caddyfile")
PUBLIC_CADDY_SHA = "0788282cee590569e2a519678cc9cb4afa02c61ce29813ce27b70e1878635471"
PREVIOUS_CADDY_SHA = "2e4ba38cd67316b6469c740aee7fc4e19b9c2cc3754a1a2a92b00bb01819d23a"
NGINX_CONFIG_SHA = "17c7b5033d000547a79917f63235675bad038bb24cc02e0d920320bd69d9bc85"
CA_BUNDLE_SHA = "0e4c9a8eb123513b1c131c0aec2d3f9ddaad02b77b8af53bff30e1e7fc3c6b71"
NGINX_IMAGE = "sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949"
CADDY_IMAGE = "sha256:df7f1c2fb114453b951de51a98efc010db1655a92c2e86be6706714e2417a78d"


def hold(reason):
    print("PUBLIC_GUEST_RELEASE_HOLD:", reason)
    raise SystemExit(3)


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, url):
        return None


def fetch(url, *, body=None, timeout=15, follow=True):
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(
        url, data=body, method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with opener.open(request, timeout=timeout) as r:
            buf = r.read(32769)
            if len(buf) > 32768:
                hold("response larger than bounded audit")
            return r.status, buf, r.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1024), exc.headers.get("Location", "")


def main():
    if socket.gethostname() != "kipnerter-prod-01" or pwd.getpwuid(os.getuid()).pw_name != "kipnerter":
        hold("unexpected host or operator")
    inputs = (
        (CADDY, PUBLIC_CADDY_SHA),
        (ROOT / "Caddyfile.before", PREVIOUS_CADDY_SHA),
        (ROOT / "Caddyfile.public-candidate", PUBLIC_CADDY_SHA),
        (ROOT / "nginx.conf.prod", NGINX_CONFIG_SHA),
        (ROOT / "verified-host-ca.pem", CA_BUNDLE_SHA),
    )
    for path, expected_sha in inputs:
        if not path.is_file() or path.is_symlink() or digest(path) != expected_sha:
            hold("pinned release file missing or altered")

    caddy_source = CADDY.read_text()
    nginx_source = (ROOT / "nginx.conf.prod").read_text()
    for line in (
        "redir @lfm3_beta_entry https://preview.kipnerter.com{uri} 302",
        "handle @public_chat {", "handle @public_api {",
        "handle @public_assets {", "basic_auth {",
        "header_up X-Kipnerter-Client-IP {remote_host}",
        "header_up -Authorization",
        "reverse_proxy kipnerter-lfm3-public-gate-v01:8080",
    ):
        if line not in caddy_source:
            hold("canonical public Caddy route policy changed")
    for line in (
        "limit_req_zone $http_x_kipnerter_client_ip zone=lfm3_ip:1m rate=3r/m;",
        "limit_req_zone $server_name zone=lfm3_global:1m rate=12r/m;",
        "limit_conn lfm3_active 1;",
        "client_max_body_size 8192;",
        "limit_req_status 429;",
        "proxy_ssl_verify on;",
        "proxy_ssl_verify_depth 6;",
        "proxy_ssl_trusted_certificate /etc/nginx/verified-host-ca.pem;",
    ):
        if line not in nginx_source:
            hold("canonical edge quota or upstream TLS policy changed")

    try:
        nginx = json.loads(subprocess.check_output(
            ["docker", "inspect", "kipnerter-lfm3-public-gate-v01"], timeout=9,
            stderr=subprocess.DEVNULL))[0]
        caddy = json.loads(subprocess.check_output(
            ["docker", "inspect", "kipnerter-caddy-1"], timeout=9,
            stderr=subprocess.DEVNULL))[0]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        hold("container identity unavailable")
    nh = nginx["HostConfig"]
    if (nginx["Image"] != NGINX_IMAGE or not nginx["State"]["Running"] or
            nh["RestartPolicy"]["Name"] != "unless-stopped" or
            nh.get("PortBindings") or nh.get("ReadonlyRootfs") is not True or
            nginx["Config"].get("User") != "101:101" or
            nh.get("Memory") != 160 * 1024 * 1024 or
            nh.get("NanoCpus") != 400000000 or
            nh.get("PidsLimit") != 64 or "ALL" not in (nh.get("CapDrop") or [])):
        hold("resource-bounded private Nginx gateway identity changed")
    if caddy["Image"] != CADDY_IMAGE or not caddy["State"]["Running"]:
        hold("production Caddy identity changed")

    home, _, _ = fetch("https://kipnerter.com/")
    redirect, _, location = fetch("https://kipnerter.com/chat", follow=False)
    guest, page, _ = fetch("https://preview.kipnerter.com/chat")
    operator, _, _ = fetch("https://preview.kipnerter.com/")
    fleet, _, _ = fetch("https://preview.kipnerter.com/api/chat/fleet-status")
    ready, _, _ = fetch("https://api.kipnerter.com/health/ready")
    if ((home, redirect, guest, operator, fleet, ready) !=
            (200, 302, 200, 401, 401, 200) or
            location != "https://preview.kipnerter.com/chat" or
            b"Message Kipnerter" not in page):
        hold("public/guest/operator route separation failed")
    asset = re.search(rb'/_next/static/[^"\s<]+', page)
    if not asset:
        hold("Next.js frontend static assets missing")
    asset_path = asset.group().decode("ascii").replace("&amp;", "&")
    asset_code, _, _ = fetch("https://preview.kipnerter.com" + asset_path)
    if asset_code != 200:
        hold("new chat assets not served")

    payload = json.dumps({"messages": [{
        "role": "user", "content": "What is 2 + 2? Reply with the digit 4."
    }]}).encode("utf-8")
    start = time.monotonic()
    code, raw, _ = fetch("https://preview.kipnerter.com/api/chat/completions",
                         body=payload, timeout=40)
    latency = round((time.monotonic() - start) * 1000)
    answer = json.loads(raw) if code == 200 else {}
    reply = answer.get("reply", "")
    if (code != 200 or answer.get("model") != "LFM3-1.7B" or
            not isinstance(reply, str) or not re.search(r"\b4\b", reply) or
            "SIMULATED DEMO RESPONSE" in reply or
            "LOCAL HTTP FIXTURE" in reply or latency > 15000):
        hold("public guest failed bounded genuine-model acceptance")

    print("PUBLIC_GUEST_LFM3_RELEASE_PASS",
          "main_redirect_302=true", "guest_html_200=true",
          "guest_assets_200=true", "operator_401=true",
          "fleet_api_401=true", "main_200=true", "api_health_200=true",
          "bounded_nginx_gateway=true", "cert_verify_required=true",
          "genuine_LFM3_1_7B=true",
          "single_generation_latency_ms=" + str(latency),
          "sample_count=1")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        hold("unhandled live read-only verification failure")
