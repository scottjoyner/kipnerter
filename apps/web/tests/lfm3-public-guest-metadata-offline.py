#!/usr/bin/env python3
"""No-network behavioral tests for the public LFM3 release audit."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

AUDIT = Path(__file__).resolve().parents[3] / "scripts" / "lfm3_public_guest_audit.py"

class GuestAuditTests(unittest.TestCase):
    def run_case(self, cli, scenario=None):
        scope = {"__name__": "lfm3_guest_metadata_offline", "__file__": str(AUDIT)}
        exec(compile(AUDIT.read_text(), str(AUDIT), "exec"), scope)
        caddy = "\n".join([
            "redir @lfm3_beta_entry https://preview.kipnerter.com{uri} 302",
            "handle @native_lfm3_api {", "handle @public_chat {",
            "handle @public_api {", "handle @public_assets {",
            "basic_auth {", "header_up X-Kipnerter-Client-IP {remote_host}",
            "header_up -Authorization",
            "reverse_proxy kipnerter-lfm3-public-gate-v01:8080"
        ])
        nginx = "\n".join([
            "limit_req_zone $http_x_kipnerter_client_ip zone=lfm3_ip:1m rate=3r/m;",
            "limit_req_zone $server_name zone=lfm3_global:1m rate=12r/m;",
            "limit_conn lfm3_active 1;", "client_max_body_size 8192;",
            "limit_req_status 429;", "proxy_ssl_verify on;",
            "proxy_ssl_verify_depth 6;",
            "proxy_ssl_trusted_certificate /etc/nginx/verified-host-ca.pem;"
        ])
        call_count = {"inspect": 0, "get": 0, "post": 0}
        def digest(path):
            if scenario == "wrong_caddy_sha" and path == scope["CADDY"]:
                return "0" * 64
            return {
                scope["CADDY"]: scope["PUBLIC_CADDY_SHA"],
                scope["ROOT"] / "Caddyfile.before": scope["PREVIOUS_CADDY_SHA"],
                scope["ROOT"] / "Caddyfile.before-ios-api": scope["GUEST_BEFORE_IOS_SHA"],
                scope["ROOT"] / "Caddyfile.ios-api-candidate": scope["PUBLIC_CADDY_SHA"],
                scope["ROOT"] / "nginx.conf.prod": scope["NGINX_CONFIG_SHA"],
                scope["ROOT"] / "verified-host-ca.pem": scope["CA_BUNDLE_SHA"],
            }[path]
        def fake_inspect(command, **kwargs):
            self.assertEqual(command[:2], ["docker", "inspect"])
            self.assertEqual(kwargs["timeout"], 9)
            call_count["inspect"] += 1
            name = command[2]
            if name == "kipnerter-lfm3-public-gate-v01":
                item = {
                    "Image": scope["NGINX_IMAGE"], "State": {"Running": True},
                    "Config": {"User": "101:101"},
                    "HostConfig": {
                        "RestartPolicy": {"Name": "unless-stopped"},
                        "PortBindings": {}, "ReadonlyRootfs": True,
                        "Memory": 160 * 1024 * 1024, "NanoCpus": 400000000,
                        "PidsLimit": 64, "CapDrop": ["ALL"],
                    },
                }
            elif name == "kipnerter-caddy-1":
                item = {"Image": scope["CADDY_IMAGE"], "State": {"Running": True}}
            else:
                self.fail("unrecognized container")
            if scenario == "oversized_gateway" and name == "kipnerter-lfm3-public-gate-v01":
                item["HostConfig"]["Memory"] += 1
            return json.dumps([item]).encode()
        def fake_fetch(url, *, body=None, timeout=15, follow=True):
            if body is not None:
                self.assertEqual(url, "https://kipnerter.com/api/chat/completions")
                self.assertFalse(follow)
                self.assertLessEqual(timeout, 40)
                call_count["post"] += 1
                return 200, json.dumps({"model": "LFM3-1.7B", "reply": "4"}).encode(), ""
            call_count["get"] += 1
            cases = {
                "https://kipnerter.com/": (200, b"ok", ""),
                "https://kipnerter.com/chat": (302, b"", "https://preview.kipnerter.com/chat"),
                "https://preview.kipnerter.com/chat": (200, b'Message Kipnerter /_next/static/chunk.js"', ""),
                "https://preview.kipnerter.com/": (401, b"", ""),
                "https://preview.kipnerter.com/api/chat/fleet-status": (401, b"", ""),
                "https://api.kipnerter.com/health/ready": (200, b"", ""),
                "https://kipnerter.com/api/chat/completions": (403, b"", ""),
                "https://preview.kipnerter.com/_next/static/chunk.js": (200, b"", ""),
            }
            self.assertIn(url, cases)
            if url == "https://kipnerter.com/chat":
                self.assertFalse(follow)
            if scenario == "operator_exposed" and url == "https://preview.kipnerter.com/":
                return 200, b"exposed", ""
            return cases[url]
        scope["digest"] = digest
        scope["fetch"] = fake_fetch
        content = io.StringIO()
        with (
            mock.patch("sys.argv", [str(AUDIT), *cli]),
            mock.patch("socket.gethostname", return_value="kipnerter-prod-01"),
            mock.patch("pwd.getpwuid", return_value=SimpleNamespace(pw_name="kipnerter")),
            mock.patch("os.getuid", return_value=1001),
            mock.patch.object(Path, "is_file", return_value=True),
            mock.patch.object(Path, "is_symlink", return_value=False),
            mock.patch.object(Path, "read_text", autospec=True,
                              side_effect=lambda path: nginx if path.name == "nginx.conf.prod" else caddy),
            mock.patch("subprocess.check_output", side_effect=fake_inspect),
            redirect_stdout(content),
        ):
            code = 0
            try:
                scope["main"]()
            except SystemExit as ex:
                code = ex.code
        return code, call_count, content.getvalue()

    def test_metadata_only_has_zero_model_requests(self):
        code, count, out = self.run_case(["--metadata-only"])
        self.assertEqual(code, 0)
        self.assertEqual(count, {"inspect": 2, "get": 8, "post": 0})
        self.assertIn("PUBLIC_GUEST_METADATA_PASS", out)
        self.assertIn("model_requests=0 sample_count=0", out)
        self.assertNotIn("single_generation_latency_ms=", out)

    def test_default_full_audit_retains_single_model_request(self):
        code, count, out = self.run_case([])
        self.assertEqual(code, 0)
        self.assertEqual(count, {"inspect": 2, "get": 8, "post": 1})
        self.assertIn("PUBLIC_GUEST_LFM3_RELEASE_PASS", out)
        self.assertIn("sample_count=1", out)
        self.assertNotIn("PUBLIC_GUEST_METADATA_PASS", out)

    def test_wrong_live_caddy_hash_fails_without_generation(self):
        code, count, out = self.run_case(["--metadata-only"], "wrong_caddy_sha")
        self.assertEqual(code, 3)
        self.assertEqual(count["post"], 0)
        self.assertEqual(count["inspect"], 0)
        self.assertIn("PUBLIC_GUEST_RELEASE_HOLD", out)

    def test_resource_limit_drift_fails_without_generation(self):
        code, count, out = self.run_case(["--metadata-only"], "oversized_gateway")
        self.assertEqual(code, 3)
        self.assertEqual(count["post"], 0)
        self.assertEqual(count["get"], 0)
        self.assertIn("PUBLIC_GUEST_RELEASE_HOLD", out)

    def test_operator_route_exposure_fails_without_generation(self):
        code, count, out = self.run_case(["--metadata-only"], "operator_exposed")
        self.assertEqual(code, 3)
        self.assertEqual(count["post"], 0)
        self.assertIn("PUBLIC_GUEST_RELEASE_HOLD", out)

    def test_unsupported_flag_fails_before_access(self):
        code, count, out = self.run_case(["--no-model"])
        self.assertEqual(code, 3)
        self.assertEqual(count, {"inspect": 0, "get": 0, "post": 0})
        self.assertIn("PUBLIC_GUEST_RELEASE_HOLD: unsupported audit arguments", out)

if __name__ == "__main__":
    unittest.main()