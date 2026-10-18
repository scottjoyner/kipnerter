"""Validate the exact private Tailscale OIDC issuer before production deployment.

No access or client tokens are sent to the discovery URL. TLS is verified by
urllib's default system trust roots. A failed check blocks release.
"""
import json
import os
import urllib.request
from urllib.parse import urlsplit

MAX_METADATA_BYTES = 65536


def _origin(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "https" or url.username or url.password
        or url.query or url.fragment
        or not url.hostname or not url.hostname.endswith(".ts.net")
        or url.port not in (None, 443)
    ):
        raise ValueError("OIDC issuer must be a tailnet HTTPS URL")
    if url.path not in ("", "/"):
        raise ValueError("OIDC issuer must use the tsidp root")
    return f"https://{url.hostname}"


def _check_endpoint(value, origin: str):
    if not isinstance(value, str):
        raise ValueError("missing OIDC discovery endpoint")
    url = urlsplit(value)
    if (
        url.scheme != "https" or url.hostname != urlsplit(origin).hostname
        or url.username or url.password or url.port not in (None, 443)
        or url.query or url.fragment
    ):
        raise ValueError("OIDC endpoint leaves pinned tsidp issuer")
    return True


def validate(issuer: str, callback_base: str, fetch=None):
    origin = _origin(issuer)
    if callback_base.rstrip("/") != "https://kipnerter.com":
        raise ValueError("unexpected public callback origin")
    discovery_url = origin + "/.well-known/openid-configuration"
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(url, timeout=7) as reply:
                if _origin(reply.geturl().split("/.well-known/")[0]) != origin:
                    raise ValueError("OIDC discovery redirected away from issuer")
                body = reply.read(MAX_METADATA_BYTES + 1)
                if len(body) > MAX_METADATA_BYTES:
                    raise ValueError("OIDC metadata exceeds size limit")
                return json.loads(body)
    metadata = fetch(discovery_url)
    if not isinstance(metadata, dict):
        raise ValueError("invalid OIDC discovery document")
    if metadata.get("issuer", "").rstrip("/") != origin:
        raise ValueError("OIDC metadata issuer mismatch")
    for item in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        _check_endpoint(metadata.get(item), origin)
    return {"validated": True, "issuer_kind": "Tailscale tsidp",
            "callback": "https://kipnerter.com/api/auth/callback/tailscale"}


if __name__ == "__main__":
    try:
        result = validate(
            os.getenv("TSIDP_ISSUER", ""),
            os.getenv("NEXTAUTH_URL", ""),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit("OIDC preflight failed: " + str(exc)) from None
    print("Tailscale OIDC discovery and callback origin verified")
