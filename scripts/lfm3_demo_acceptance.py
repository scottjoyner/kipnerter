#!/usr/bin/env python3
"""Loopback-only synthetic demo acceptance for the real Next.js LFM3 route.

This is NOT evidence of actual LFM3 inference, host custody, public ingress,
secret provisioning or readiness to deploy. No private credentials are read.
"""
import json
import os
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
MODEL = "lfm3-1.7b-demo-fixture"
SENTINEL = "4 [SIMULATED DEMO RESPONSE - NOT REAL MODEL INFERENCE]"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FixtureHandler(BaseHTTPRequestHandler):
    completions = 0
    invalid = 0

    def log_message(self, *_args):
        pass  # never print prompt contents or client headers

    def send_json(self, status, value):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            return self.send_json(200, {"data": [{"id": MODEL}]})
        return self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self.send_json(404, {"error": "not found"})
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > 8192:
            type(self).invalid += 1
            return self.send_json(413, {"error": "fixture input size"})
        try:
            payload = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeDecodeError):
            type(self).invalid += 1
            return self.send_json(400, {"error": "fixture request"})
        if (payload.get("model") != MODEL or
            not isinstance(payload.get("messages"), list) or
            self.headers.get("Authorization") or payload.get("tools")):
            type(self).invalid += 1
            return self.send_json(400, {"error": "unexpected fixture call"})
        type(self).completions += 1
        return self.send_json(200, {"id": "synthetic-only",
            "model": MODEL, "choices": [{"message": {"role": "assistant", "content": SENTINEL}}]})


def http(url, data=None):
    headers = {"X-Forwarded-For": "203.0.113.17", "Cache-Control": "no-store"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urlopen(req, timeout=8) as response:
            return response.status, response.read(150000)
    except HTTPError as exc:
        return exc.code, exc.read(150000)


@contextmanager
def server_process(port, fixture_port):
    env = os.environ.copy()
    env.update({
        "NODE_ENV": "production",
        "KIPNERTER_ENV": "staging",
        "KIPNERTER_LFM3_ENDPOINTS": json.dumps([{
            "name": "loopback_demo_only", "baseUrl": f"http://127.0.0.1:{fixture_port}",
            "model": MODEL, "adapter": "openai", "role": "interactive",
            "maxInflight": 1, "maxOutputTokens": 64
        }]),
    })
    proc = subprocess.Popen(
        ["node", "node_modules/next/dist/bin/next", "start", "-p", str(port)],
        cwd=WEB, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        yield proc
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


def assert_ready(base, proc):
    for _ in range(75):
        if proc.poll() is not None:
            raise AssertionError("isolated Next.js server exited before readiness")
        try:
            code, page = http(base + "/chat")
            if code == 200 and b"Message Kipnerter" in page:
                return
        except (URLError, TimeoutError):
            pass
        time.sleep(0.2)
    raise AssertionError("isolated Next.js did not start")


def run():
    if not (WEB / ".next").is_dir():
        raise AssertionError("run npm ci && npm run build in apps/web before the demo test")
    fixture_port, app_port = free_port(), free_port()
    while fixture_port == app_port:
        app_port = free_port()
    FixtureHandler.completions = 0
    FixtureHandler.invalid = 0
    server = ThreadingHTTPServer(("127.0.0.1", fixture_port), FixtureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with server_process(app_port, fixture_port) as proc:
            base = f"http://127.0.0.1:{app_port}"
            assert_ready(base, proc)
            for path in ("/", "/chat"):
                code, page = http(base + path)
                assert code == 200 and b"Message Kipnerter" in page and b"LFM3-1.7B" in page, path
                assert b"Sign in with Tailscale identity" not in page, path
            code, fleet = http(base + "/fleet")
            assert code == 200 and b"PRIVATE AI WORKSPACE" in fleet, "private operator login missing"
            assert b"Message Kipnerter" not in fleet, "private page replaced with public chat"

            def complete(messages, **kwargs):
                return http(base + "/api/chat/completions", {"messages": messages, **kwargs})
            valid = [{"role": "user", "content": "2+2; return 4"}]
            code, raw = complete(valid)
            payload = json.loads(raw)
            assert code == 200 and payload == {"reply": SENTINEL, "model": "LFM3-1.7B"}, (code, payload)
            assert FixtureHandler.completions == 1
            for bad, expected in [
                ({"messages": [{"role": "system", "content": "private tool call"}]}, 400),
                ({"messages": valid, "tools": [{"name": "shell"}]}, 400),
                ({"messages": [{"role": "user", "content": "x" * 2000}]}, 413),
            ]:
                code, _ = http(base + "/api/chat/completions", bad)
                assert code == expected, (code, expected)
            assert FixtureHandler.completions == 1, "rejected requests must not reach model fixture"
            codes = [complete(valid)[0] for _ in range(10)]
            assert 429 in codes, codes
            assert FixtureHandler.invalid == 0, "gateway leaked unexpected model call shape"
            print("PASS: real Next.js / and /chat, protected /fleet, exact model contract, 400/413, shared-IP 429")
            print(f"SIMULATED_FIXTURE_ONLY=true; accepted_model_calls={FixtureHandler.completions}")
            print("No live LFM3, production Caddy, private secrets, public traffic or Apple device exercised.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    run()
