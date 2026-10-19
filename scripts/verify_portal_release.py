#!/usr/bin/env python3
"""Fail-closed public release gate: never mark a 404 or unconfigured portal as healthy.

No cookies, OAuth client secrets, or gateway credentials are sent. This checks
only public landing/config and anonymous-denial contracts; real operator sign-in
and production-private telemetry remain independent release gates.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

MAX_BYTES = 131072


def _fetch(url):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "application/json,text/html"})
    try:
        with opener.open(request, timeout=8) as reply:
            content = reply.read(MAX_BYTES + 1)
            return reply.status, content, reply.geturl()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(MAX_BYTES + 1), exc.geturl()


def check(public_url, api_url, expected_sha, fetch=None):
    """Return failure descriptions without exposing any response-body secrets."""
    fetch = fetch or _fetch
    failures = []
    expected = (
        (public_url + "/chat", 200),
        (public_url + "/api/auth/providers", 200),
        (public_url + "/api/release", 200),
        (public_url + "/api/portal/live", 401),
        (public_url + "/api/portal/traces", 401),
        (api_url + "/health", 200),
        (api_url + "/api/v1/release", 200),
        (api_url + "/health/live", 200),
        (api_url + "/health/ready", 200),
        (api_url + "/api/v1/control-plane/overview", 401),
        (api_url + "/api/v1/control-plane/traces", 401),
    )
    for url, required in expected:
        label = urlparse(url).path
        try:
            code, body, final = fetch(url)
            if len(body) > MAX_BYTES or final != url:
                failures.append(f"{label}: oversized or redirected response")
                continue
            if code != required:
                failures.append(f"{label}: HTTP {code}, expected {required}")
                continue
            if label in ("/api/release", "/api/v1/release"):
                release = json.loads(body)
                source = "kipnerter-web" if label == "/api/release" else "kipnerter-api"
                if (not isinstance(release, dict) or
                        set(release) != {"source", "revision"} or
                        release.get("source") != source or
                        release.get("revision") != expected_sha):
                    failures.append(f"{label}: incorrect deployed source revision")
            if label == "/chat":
                html = body.decode("utf-8")
                if ("PRIVATE AI WORKSPACE" not in html or
                    "Sign in with Tailscale identity" not in html or
                    "Fleet login is not yet configured" in html):
                    failures.append("/chat: login not configured or wrong build")
            if label == "/api/auth/providers":
                data = json.loads(body)
                if not isinstance(data, dict) or not isinstance(data.get("tailscale"), dict):
                    failures.append("/api/auth/providers: Tailscale provider missing")
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            failures.append(f"{label}: unreachable or invalid response ({type(exc).__name__})")
    return failures


def verify(public_url, api_url, expected_sha, attempts=1, interval=0, fetch=None, sleep=None):
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise ValueError("release attestation requires exact 40-character Git SHA")
    if attempts < 1 or interval < 0:
        raise ValueError("invalid release verification window")
    if not (public_url.startswith("https://") and api_url.startswith("https://")):
        raise ValueError("release endpoints must use HTTPS")
    sleep = sleep or time.sleep
    problems = ["not started"]
    for attempt in range(attempts):
        problems = check(public_url.rstrip("/"), api_url.rstrip("/"), expected_sha, fetch)
        if not problems:
            return attempt + 1
        if attempt < attempts - 1:
            sleep(interval)
    raise RuntimeError("release NOT healthy: " + "; ".join(problems))


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--public-url", default="https://kipnerter.com")
    cli.add_argument("--api-url", default="https://api.kipnerter.com")
    cli.add_argument("--expected-sha", required=True)
    cli.add_argument("--attempts", type=int, default=30)
    cli.add_argument("--interval", type=int, default=10)
    arg = cli.parse_args()
    try:
        retries = verify(arg.public_url, arg.api_url, arg.expected_sha, arg.attempts, arg.interval)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"Public portal release endpoints verified after {retries} check(s)")
