import unittest
from scripts.portal_oidc_preflight import validate

ORIGIN = "https://idp.tailcb8954.ts.net"


def sample(url):
    assert url == ORIGIN + "/.well-known/openid-configuration"
    return {
        "issuer": ORIGIN,
        "authorization_endpoint": ORIGIN + "/authorize",
        "token_endpoint": ORIGIN + "/token",
        "jwks_uri": ORIGIN + "/.well-known/jwks.json",
    }


class OidcPreflightTests(unittest.TestCase):
    def test_valid_tailnet_provider(self):
        self.assertTrue(validate(ORIGIN, "https://kipnerter.com", sample)["validated"])

    def test_bad_issuer_and_callback_denied(self):
        for issuer in ("https://evil.com", "http://idp.tailcb8954.ts.net",
                       "https://idp.tailcb8954.ts.net.evil.org",
                       "https://idp.tailcb8954.ts.net/other",
                       "https://idp.tailcb8954.ts.net:8443"):
            with self.subTest(issuer=issuer), self.assertRaises(ValueError):
                validate(issuer, "https://kipnerter.com", sample)
        with self.assertRaises(ValueError):
            validate(ORIGIN, "https://evil.com", sample)

    def test_unexpected_oidc_keys_denied(self):
        for key, value in (
            ("issuer", "https://other.tailcb8954.ts.net"),
            ("jwks_uri", "https://attacker.com/jwks"),
            ("token_endpoint", "http://idp.tailcb8954.ts.net/token"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                def tampered(url):
                    data = sample(url)
                    data[key] = value
                    return data
                validate(ORIGIN, "https://kipnerter.com", tampered)


if __name__ == "__main__":
    unittest.main()
