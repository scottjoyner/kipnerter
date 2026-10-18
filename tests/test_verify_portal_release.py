import json
import unittest
from scripts.verify_portal_release import check, verify

PUBLIC = "https://kipnerter.com"
API = "https://api.kipnerter.com"
READY_HTML = b"PRIVATE AI WORKSPACE <a>Sign in with Tailscale identity</a>"


def fixture(broken=None):
    broken = broken or {}
    defaults = {
        PUBLIC + "/chat": (200, READY_HTML),
        PUBLIC + "/api/auth/providers": (200, json.dumps({"tailscale": {"id": "tailscale"}}).encode()),
        PUBLIC + "/api/portal/live": (401, b"{}"),
        PUBLIC + "/api/portal/traces": (401, b"{}"),
        API + "/health": (200, b"{}"),
        API + "/health/live": (200, b"{}"),
        API + "/health/ready": (200, b"{}"),
        API + "/api/v1/control-plane/overview": (401, b"{}"),
        API + "/api/v1/control-plane/traces": (401, b"{}"),
    }
    defaults.update(broken)
    def fetch(url):
        code, data = defaults[url]
        return code, data, url
    return fetch


class PortalReleaseTests(unittest.TestCase):
    def test_success_requires_configured_identity_and_anonymous_denial(self):
        self.assertEqual(check(PUBLIC, API, fixture()), [])
        self.assertEqual(verify(PUBLIC, API, fetch=fixture()), 1)

    def test_missing_chat_route_is_a_hard_release_failure(self):
        fetch = fixture({PUBLIC + "/chat": (404, b"not found")})
        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            verify(PUBLIC, API, attempts=3, interval=0, fetch=fetch, sleep=lambda *_: None)

    def test_setup_notice_or_broken_provider_blocks_release(self):
        for change in (
            {PUBLIC + "/chat": (200, b"PRIVATE AI WORKSPACE Fleet login is not yet configured")},
            {PUBLIC + "/api/auth/providers": (200, b"{}")},
            {PUBLIC + "/api/portal/live": (503, b"identity not configured")},
            {API + "/api/v1/control-plane/traces": (200, b"SECRET")},
        ):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                verify(PUBLIC, API, fetch=fixture(change))

    def test_retries_then_succeeds_or_fails_closed(self):
        failed = fixture({PUBLIC + "/chat": (404, b"missing")})
        passed = fixture()
        calls = [0]
        def fetch(url):
            if url == PUBLIC + "/chat":
                calls[0] += 1
            return failed(url) if calls[0] == 1 else passed(url)
        self.assertEqual(verify(PUBLIC, API, attempts=3, interval=0,
                                fetch=fetch, sleep=lambda *_: None), 2)

    def test_rejects_redirects_oversized_payload_and_http(self):
        def redirect(url):
            if url == PUBLIC + "/chat":
                return (200, READY_HTML, PUBLIC + "/other")
            return fixture()(url)
        self.assertTrue(check(PUBLIC, API, redirect))
        with self.assertRaises(ValueError):
            verify("http://kipnerter.com", API)


if __name__ == "__main__":
    unittest.main()
