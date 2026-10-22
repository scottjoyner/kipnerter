#!/usr/bin/env python3
"""Exercise the real NextAuth/BFF/SSE -> FastAPI -> private observer path.

Runs *only* on loopback with synthetic operator identity and ephemeral web/API
credentials. Optional --real-observer uses existing root-independent local
observer secret; never emits secrets, signed cookies, or raw trace records.
Does not provision an IdP, change Tailscale Serve, deploy, or run agents.
"""
import argparse
import json
import os
import pwd
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BROWSER_EMAIL = "portal-smoke@invalid.test"
BROWSER_SUBJECT = "synthetic-operator-sub-8"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url, cookie=None, timeout=10):
    headers = {"Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read(131072), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(131072), dict(exc.headers)


@contextmanager
def serving(command, cwd, env):
    with open(os.devnull, "w") as null:
        proc = subprocess.Popen(
            command, cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=null, stderr=null,
            start_new_session=True,
        )
        try:
            yield proc
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=6)


def wait_for(url, process, attempts=30):
    for _ in range(attempts):
        if process.poll() is not None:
            raise RuntimeError("Local smoke server exited early")
        try:
            code, _, _ = request(url, timeout=1)
            if code in (200, 401, 503):
                return
        except (OSError, TimeoutError):
            pass
        time.sleep(.4)
    raise RuntimeError("Local smoke server did not become ready")


def make_cookie(web_env, subject=BROWSER_SUBJECT, max_age=900):
    script = """
    (async()=>{const {encode}=require('next-auth/jwt');
      const t=await encode({
        token:{sub:process.env.TEST_SUBJECT,email:process.env.TEST_EMAIL,
          name:'Synthetic smoke identity'},
        secret:process.env.NEXTAUTH_SECRET,
        maxAge:Number(process.env.TEST_MAX_AGE)
      });
      process.stdout.write(t);
    })().catch(()=>process.exit(1))
    """
    env = web_env.copy()
    env["TEST_SUBJECT"], env["TEST_EMAIL"] = subject, BROWSER_EMAIL
    env["TEST_MAX_AGE"] = str(max_age)
    token = subprocess.check_output(
        ["node", "-e", script], cwd=ROOT / "apps/web", env=env, text=True, timeout=10,
    )
    return "__Secure-next-auth.session-token=" + token


def assert_no_private_data(payload):
    lowered = payload.lower()
    for marker in (b"basic_auth_pass", b"tailnetip", b"authorization", b"raw_prompt"):
        if marker in lowered:
            raise AssertionError("Sensitive metadata field exported")
    if len(payload) >= 131072:
        raise AssertionError("Response exceeded bounded-read limit")


def run(real_observer, staging=False):
    api_port, web_port = free_port(), free_port()
    while web_port == api_port:
        web_port = free_port()
    key, secret = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    api_env = os.environ.copy()
    api_env.update({
        "KIPNERTER_RELEASE_SHA": "a" * 40,
        "KIPNERTER_GATEWAY_TOKEN": key,
        "ASSISTX_BASE_URL": "", "ASSISTX_MONITOR_USER": "", "ASSISTX_MONITOR_PASSWORD": "",
        "SOPHIA_BASE_URL": "", "HERMES_BASE_URL": "", "OPENCODE_BASE_URL": "",
        "LMSTUDIO_BASE_URL": "", "FLEET_MONITOR_BASE_URL": "", "FLEET_MONITOR_TOKEN": "",
    })
    if real_observer:
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        record = (home / ".config/kipnerter-observer/observer.env").read_text().splitlines()
        value = next(x.partition("=")[2] for x in record if x.startswith("FLEET_MONITOR_TOKEN="))
        if len(value) < 32:
            raise RuntimeError("Observer test credential not configured")
        api_env["FLEET_MONITOR_TOKEN"] = value
        api_env["FLEET_MONITOR_BASE_URL"] = "https://x1-370.tailcb8954.ts.net:8448"
    web_env = os.environ.copy()
    web_env.update({
        "KIPNERTER_RELEASE_SHA": "a" * 40,
        "NEXTAUTH_URL": "https://staging.kipnerter.com" if staging else "https://kipnerter.com",
        "KIPNERTER_ENV": "staging" if staging else "production",
        "NEXTAUTH_SECRET": secret,
        "TSIDP_ISSUER": "https://idp.synthetic-tailnet.ts.net",
        "TSIDP_CLIENT_ID": "portal-smoke-only",
        "TSIDP_CLIENT_SECRET": "portal-smoke-not-valid",
        "KIPNERTER_ALLOWED_EMAILS": BROWSER_EMAIL,
        "KIPNERTER_ALLOWED_TSIDP_SUBJECTS": BROWSER_SUBJECT,
        "KIPNERTER_GATEWAY_TOKEN": key,
        "KIPNERTER_INTERNAL_API_URL": f"http://127.0.0.1:{api_port}",
        "PORT": str(web_port), "NODE_ENV": "production",
    })
    with serving(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(api_port)],
        ROOT / "apps/api", api_env,
    ) as api:
        wait_for(f"http://127.0.0.1:{api_port}/health", api)
        with serving(
            ["node", "node_modules/next/dist/bin/next", "start", "-p", str(web_port)],
            ROOT / "apps/web", web_env,
        ) as web:
            base = f"http://127.0.0.1:{web_port}"
            wait_for(base + "/chat", web)
            code, page, _ = request(base + "/chat")
            if code != 200 or b"Sign in with Tailscale identity" not in page or b"Fleet login is not yet configured" in page:
                raise AssertionError("Deployment-scoped NextAuth provider is not available")
            for url, source in (
                (base + "/api/release", "kipnerter-web"),
                (f"http://127.0.0.1:{api_port}/api/v1/release", "kipnerter-api"),
            ):
                code, raw, headers = request(url)
                if code != 200:
                    raise AssertionError(f"Source-pinned revision endpoint unavailable: {source}")
                evidence = json.loads(raw)
                if evidence != {"source": source, "revision": "a" * 40}:
                    raise AssertionError(f"Wrong release image identity: {source}")
                cache_control = next((v for k, v in headers.items()
                                      if k.lower() == "cache-control"), "")
                if "no-store" not in cache_control.lower():
                    raise AssertionError(f"Cacheable release identity: {source}")
            print("exact web/API synthetic release SHA verified")
            cookie = make_cookie(web_env)
            for path in ("/api/portal/nodes", "/api/portal/traces", "/api/portal/live"):
                code, _, _ = request(base + path)
                if code != 401:
                    raise AssertionError(f"Anonymous {path} returned {code}, expected 401")
            print("anonymous BFF and stream denied: 401")
            forged = make_cookie(web_env, "unapproved-signed-subject")
            for path in ("/api/portal/nodes", "/api/portal/traces", "/api/portal/live"):
                code, _, _ = request(base + path, forged)
                if code != 401:
                    raise AssertionError(f"Non-allowlisted signed subject {path} returned {code}")
            print("non-allowlisted signed subject denied: 401")
            expired = make_cookie(web_env, max_age=-60)
            for path in ("/api/portal/nodes", "/api/portal/live"):
                code, _, _ = request(base + path, expired)
                if code != 401:
                    raise AssertionError(f"Expired synthetic session {path} returned {code}")
            print("expired signed session denied: 401")
            for path in ("/api/portal/nodes", "/api/portal/models", "/api/portal/sessions", "/api/portal/traces"):
                code, body, headers = request(base + path, cookie)
                if code != 200:
                    raise AssertionError(f"Signed synthetic session {path} returned {code}")
                value = json.loads(body)
                assert_no_private_data(body)
                cache = next((value for name, value in headers.items()
                              if name.lower() == "cache-control"), "")
                if "private" not in cache or "no-store" not in cache:
                    raise AssertionError("Missing private no-store cache policy")
                if real_observer and path == "/api/portal/nodes":
                    assert value.get("tailscale_status") == "live" and value.get("nodes")
                if real_observer and path == "/api/portal/models":
                    assert value.get("source") == "multiple_read_only_sources"
                    assert value.get("assistx_status") in ("reported", "reported_empty")
                    # Production's strict release gate requires a fresh
                    # runtime catalog, but a live observer smoke must also
                    # verify correct degraded behavior when LM Studio is down.
                    runtime_status = value.get("runtime_status")
                    assert runtime_status in ("reported", "reported_empty", "unavailable"), runtime_status
                    runtime_rows = [m for m in value.get("models", [])
                                    if m.get("source") == "lmstudio_native_catalog"]
                    if runtime_status == "reported":
                        assert runtime_rows, "reported runtime with no catalog evidence"
                    elif runtime_status in ("unavailable", "reported_empty"):
                        assert not runtime_rows, "fabricated runtime catalog from unavailable source"
                        print("LM Studio source:", runtime_status, "(no inferred model residency)")
                    assert value.get("fleet_runtime_status") == "reported"
                    assert len(value.get("fleet_runtime_nodes",[])) == 6
                    assert any(r.get("node") == "beelink" for r in value["fleet_runtime_nodes"])
                    assert value.get("status") in ("reported", "reported_empty")
                if real_observer and path == "/api/portal/nodes":
                    assert value.get("assistx_status") in ("reported", "reported_empty")
                if real_observer and path == "/api/portal/sessions":
                    assert value.get("sessions")
                if real_observer and path == "/api/portal/traces":
                    assert value.get("source") == "assistx_trace_index" and value.get("traces")
                print(f"signed session {path}: {code} {value.get('status', 'ok')}")
            # Read the initial bounded SSE snapshot; terminate on the first event
            # instead of keeping an idle stream alive.
            req = urllib.request.Request(base + "/api/portal/live",
                                         headers={"Cookie": cookie, "Accept":"text/event-stream"})
            with urllib.request.urlopen(req, timeout=20) as stream:
                if stream.status != 200 or "text/event-stream" not in stream.headers.get("Content-Type", ""):
                    raise AssertionError("SSE missing event stream headers")
                event = None
                for _ in range(25):
                    line = stream.readline(131072)
                    if line.startswith(b"data: "):
                        event = json.loads(line[6:])
                        break
                if event is None or "traces" not in event or "nodes" not in event:
                    raise AssertionError("No unified event snapshot")
                if real_observer and (
                    event["traces"].get("source") != "assistx_trace_index"
                    or event["nodes"].get("tailscale_status") != "live"
                    or event["models"].get("source") != "multiple_read_only_sources"
                    or event["models"].get("fleet_runtime_status") != "reported"
                ):
                    raise AssertionError("SSE did not include live private observer data")
                print("authenticated SSE: unified snapshot returned")
            # Open 8 simultaneous streams, verify the ninth is rejected,
            # disconnect all clients and check the slots are reclaimed.
            opened = []
            try:
                for idx in range(8):
                    stream_req = urllib.request.Request(
                        base + "/api/portal/live",
                        headers={"Cookie":cookie, "Accept":"text/event-stream"},
                    )
                    stream = urllib.request.urlopen(stream_req, timeout=15)
                    if stream.status != 200:
                        raise AssertionError(f"Stream quota occupied early at slot {idx}")
                    opened.append(stream)
                limit_code, _, _ = request(base + "/api/portal/live", cookie, timeout=5)
                if limit_code != 429:
                    raise AssertionError(f"Open-stream cap did not reject 9th stream: {limit_code}")
                print("SSE capacity: ninth connection denied with 429")
            finally:
                for stream in opened:
                    stream.close()
            time.sleep(1)
            probe = urllib.request.Request(base + "/api/portal/live",
                       headers={"Cookie":cookie, "Accept":"text/event-stream"})
            with urllib.request.urlopen(probe, timeout=15) as stream:
                if stream.status != 200:
                    raise AssertionError("Stream slot not recovered after disconnect")
            print("SSE disconnected-client capacity reclaimed")
    print("PASS: isolated end-to-end portal smoke; no deployment or agent execution")


if __name__ == "__main__":
    arg = argparse.ArgumentParser()
    arg.add_argument("--real-observer", action="store_true")
    arg.add_argument("--staging", action="store_true")
    options = arg.parse_args()
    try:
        run(options.real_observer, options.staging)
    except Exception as exc:
        print(f"FAIL: portal end-to-end smoke: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
