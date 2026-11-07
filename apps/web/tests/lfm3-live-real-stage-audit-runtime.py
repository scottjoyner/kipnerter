#!/usr/bin/env python3
"""Offline-only behavioral regression for the live LFM3 audit.

All Docker calls and HTTP requests are intercepted. Nothing reaches a host.
"""
import io
import json
import runpy
import subprocess
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

AUDIT = Path(__file__).resolve().parents[3] / "scripts" / "lfm3_local_cpu_readonly_audit.py"
EXPECTED_IMAGES = {
    "kipnerter-lfm3-local-web": "sha256:e539c1b888e1148ff34ce00d50ac8a9638b7ff6d6df8918ce27b429026804587",
    "kipnerter-lfm3-local-cpu": "sha256:c0a11067c72bb1eb330b8bddbf9869274c195e596bf4fae55fd527102e644b85",
}

class FakeResponse:
    def __init__(self, body, status=200):
        self.status = status
        self.stream = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()

    def read(self, size=-1):
        return self.stream.read(size)


class AuditBehaviorTests(unittest.TestCase):
    def run_case(self, events):
        events = iter(events)
        count = {"generation": 0, "browser": 0, "docker": 0}
        clock = iter(range(1_000_000_000, 99_000_000_000, 123_000_000))
        output = io.StringIO()

        def fake_inspect(args, **kwargs):
            self.assertEqual(args[:2], ["docker", "inspect"])
            self.assertEqual(kwargs["timeout"], 12)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            name = args[2]
            self.assertIn(name, EXPECTED_IMAGES)
            count["docker"] += 1
            model = name.endswith("-cpu")
            networks = {"stage_model_only": {}}
            if not model:
                networks["stage_web_loopback"] = {}
            obj = {
                "Image": EXPECTED_IMAGES[name],
                "State": {"Running": True, "OOMKilled": False},
                "HostConfig": {"Memory": (1536 if model else 384) * 1024 * 1024},
                "Config": {"Labels": {"com.docker.compose.project": "kipnerter-lfm3-local-real"}},
                "NetworkSettings": {
                    "Networks": networks,
                    "Ports": {} if model else {
                        "3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3356"}]
                    },
                },
            }
            return json.dumps([obj]).encode()

        def fake_http(req, timeout):
            if isinstance(req, str):
                self.assertEqual(req, "http://127.0.0.1:3356/chat")
                self.assertEqual(timeout, 10)
                count["browser"] += 1
                return FakeResponse(b"<main>Message Kipnerter</main>")
            self.assertIsInstance(req, urllib.request.Request)
            self.assertEqual(req.get_method(), "POST")
            self.assertEqual(req.full_url, "http://127.0.0.1:3356/api/chat/completions")
            self.assertEqual(timeout, 54)
            count["generation"] += 1
            event = next(events, "UNEXPECTED_EXTRA_REQUEST")
            if isinstance(event, int):
                raise urllib.error.HTTPError(req.full_url, event, "offline mock", None, None)
            if event == "valid":
                return FakeResponse(json.dumps({"model": "LFM3-1.7B", "reply": "4"}).encode())
            if event == "wrong_model":
                return FakeResponse(json.dumps({"model": "fake", "reply": "4"}).encode())
            if event == "fixture":
                return FakeResponse(json.dumps({"model": "LFM3-1.7B",
                                                "reply": "4 LOCAL HTTP FIXTURE"}).encode())
            if event == "oversized":
                return FakeResponse(b"x" * 32769)
            if event == "bad_json":
                return FakeResponse(b"not json")
            self.fail("unexpected extra generation request or scenario: " + str(event))

        with (
            mock.patch("subprocess.run", return_value=SimpleNamespace(stdout="kipnerter")) as identity,
            mock.patch("subprocess.check_output", side_effect=fake_inspect),
            mock.patch("urllib.request.urlopen", side_effect=fake_http),
            mock.patch("time.monotonic_ns", side_effect=lambda: next(clock)),
            mock.patch("time.sleep") as sleep,
            redirect_stdout(output),
        ):
            exit_code = 0
            try:
                runpy.run_path(str(AUDIT), run_name="__main__")
            except SystemExit as err:
                exit_code = err.code
            identity.assert_called_once_with(["id", "-un"], capture_output=True, text=True)
            sleeps = sleep.call_count
        self.assertEqual(count["browser"], 1)
        self.assertEqual(count["docker"], 2)
        return exit_code, count["generation"], sleeps, output.getvalue()

    def assert_hold(self, events, expected_attempts, expected_sleeps=0):
        code, attempts, sleeps, output = self.run_case(events)
        self.assertEqual((code, attempts, sleeps),
                         (3, expected_attempts, expected_sleeps))
        self.assertIn("HOLD:", output)
        self.assertNotIn("successful_generation_request_latency_ms=", output)
        self.assertNotIn("LIVE_REAL_LFM3_STAGE_PASS", output)

    def test_first_attempt_success_is_one_sample(self):
        code, attempts, sleeps, output = self.run_case(["valid"])
        self.assertEqual((code, attempts, sleeps), (0, 1, 0))
        self.assertIn("successful_generation_request_latency_ms=123 attempt_count=1 sample_count=1", output)
        self.assertEqual(output.count("sample_count=1"), 1)

    def test_429_retry_records_success_only(self):
        code, attempts, sleeps, output = self.run_case([429, "valid"])
        self.assertEqual((code, attempts, sleeps), (0, 2, 1))
        self.assertIn("successful_generation_request_latency_ms=123 attempt_count=2 sample_count=1", output)

    def test_503_retry_records_success_only(self):
        code, attempts, sleeps, output = self.run_case([503, "valid"])
        self.assertEqual((code, attempts, sleeps), (0, 2, 1))
        self.assertIn("successful_generation_request_latency_ms=123 attempt_count=2 sample_count=1", output)

    def test_fifth_attempt_succeeds_but_only_one_sample(self):
        code, attempts, sleeps, output = self.run_case([429, 503, 429, 503, "valid"])
        self.assertEqual((code, attempts, sleeps), (0, 5, 4))
        self.assertIn("attempt_count=5 sample_count=1", output)

    def test_exhausted_retries_fail_closed(self):
        self.assert_hold([429, 503, 429, 503, 429], 5, 4)

    def test_non_retryable_error_never_retries(self):
        self.assert_hold([401], 1)

    def test_wrong_model_never_produces_sample(self):
        self.assert_hold(["wrong_model"], 1)

    def test_fixture_response_never_produces_sample(self):
        self.assert_hold(["fixture"], 1)

    def test_oversized_response_never_produces_sample(self):
        self.assert_hold(["oversized"], 1)

    def test_invalid_json_never_produces_sample(self):
        self.assert_hold(["bad_json"], 1)


if __name__ == "__main__":
    unittest.main()
