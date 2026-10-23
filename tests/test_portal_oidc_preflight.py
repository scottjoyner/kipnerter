import io
import json
import unittest
from unittest.mock import patch
from scripts.portal_oidc_preflight import validate, PRIVATE_PREVIEW_TSIDP_ISSUER, PRIVATE_TAILNET_PREVIEW_ORIGIN

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

    def test_staging_is_distinct_and_requires_its_own_callback(self):
        stage = validate(ORIGIN, "https://staging.kipnerter.com", sample, "staging")
        self.assertEqual(stage["callback"], "https://staging.kipnerter.com/api/auth/callback/tailscale")
        with self.assertRaises(ValueError):
            validate(ORIGIN, "https://kipnerter.com", sample, "staging")
        with self.assertRaises(ValueError):
            validate(ORIGIN, "https://staging.kipnerter.com", sample, "production")

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

    def test_private_preview_accepts_only_exact_tsidp_origin_and_callback(self):
        def private_discovery(url):
            self.assertEqual(url, PRIVATE_PREVIEW_TSIDP_ISSUER + "/.well-known/openid-configuration")
            return {"issuer": PRIVATE_PREVIEW_TSIDP_ISSUER,
                    "authorization_endpoint": PRIVATE_PREVIEW_TSIDP_ISSUER + "/authorize",
                    "token_endpoint": PRIVATE_PREVIEW_TSIDP_ISSUER + "/token",
                    "jwks_uri": PRIVATE_PREVIEW_TSIDP_ISSUER + "/.well-known/jwks.json"}
        report = validate(PRIVATE_PREVIEW_TSIDP_ISSUER, PRIVATE_TAILNET_PREVIEW_ORIGIN,
                          private_discovery, environment="tailnet-preview")
        self.assertEqual(report["callback"],PRIVATE_TAILNET_PREVIEW_ORIGIN + "/api/auth/callback/tailscale")
        self.assertTrue(report["validated"])
        for issuer in (ORIGIN,"https://idp.other-tailnet.ts.net",
                       "https://kipnerter-idp-staging.tailcb8954.ts.net:8443",
                       "https://kipnerter-idp-staging.tailcb8954.ts.net.evil.test"):
            with self.subTest(issuer=issuer),self.assertRaises(ValueError):
                validate(issuer, PRIVATE_TAILNET_PREVIEW_ORIGIN,private_discovery,"tailnet-preview")
        for origin in ("https://kipnerter.com", "https://staging.kipnerter.com",
                       "https://x1-370.tailcb8954.ts.net", "http://x1-370.tailcb8954.ts.net:8449",
                       "https://x1-370.tailcb8954.ts.net:8448",
                       PRIVATE_TAILNET_PREVIEW_ORIGIN+"/chat"):
            with self.subTest(callback=origin),self.assertRaises(ValueError):
                validate(PRIVATE_PREVIEW_TSIDP_ISSUER,origin,private_discovery,"tailnet-preview")

    def test_discovery_requires_exact_metadata_issuer(self):
        def tampered(url):
            value=sample(url)
            value['issuer']=ORIGIN + '/'
            return value
        with self.assertRaisesRegex(ValueError,'issuer mismatch'):
            validate(ORIGIN,'https://kipnerter.com',tampered)
        def nonstring(url):
            value=sample(url)
            value['issuer']=1
            return value
        with self.assertRaisesRegex(ValueError,'issuer mismatch'):
            validate(ORIGIN,'https://kipnerter.com',nonstring)

    def test_discovery_rejects_empty_or_foreign_oidc_endpoints(self):
        for value in (None,123,'http://idp.tailcb8954.ts.net/token',
                      'https://evil.ts.net/token',
                      'https://idp.tailcb8954.ts.net:9443/token',
                      'https://token:secret@idp.tailcb8954.ts.net/token',
                      'https://idp.tailcb8954.ts.net/token?callback=evil',
                      'https://idp.tailcb8954.ts.net/token#fragment'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                def altered(url):
                    x=sample(url);x['token_endpoint']=value;return x
                validate(ORIGIN,'https://kipnerter.com',altered)

    def test_no_redirect_and_bounded_metadata_in_live_fetch_path(self):
        discovery=ORIGIN+'/.well-known/openid-configuration'
        class Response:
            status=200
            def __init__(self,payload,redirect=None):
                self.body=io.BytesIO(payload)
                self.target=redirect or discovery
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def geturl(self):return self.target
            def read(self,length):return self.body.read(length)
        class Opener:
            def __init__(self,response):self.response=response
            def open(self,url,timeout=7):
                assert url==discovery and timeout==7
                return self.response
        payload=json.dumps(sample(discovery)).encode()
        with patch('scripts.portal_oidc_preflight.urllib.request.build_opener',return_value=Opener(Response(payload))):
            self.assertTrue(validate(ORIGIN,'https://kipnerter.com')['validated'])
        for response in (
            Response(payload,redirect=ORIGIN + '/redirected-discovery'),
            Response(payload,redirect='https://malicious.ts.net/.well-known/openid-configuration'),
            Response(b'x'*65537),
            Response(b'{"issuer":'+json.dumps(ORIGIN).encode()+b',"issuer":'+json.dumps(ORIGIN).encode()+b'}'),
        ):
            with self.subTest(url=response.target),self.assertRaises(ValueError):
                with patch('scripts.portal_oidc_preflight.urllib.request.build_opener',return_value=Opener(response)):
                    validate(ORIGIN,'https://kipnerter.com')

    def test_network_redirection_handler_does_not_follow(self):
        class RefuseOpener:
            def open(self,*args,**kwargs):
                raise AssertionError('unexpected HTTP read after redirect')
        def hook(*handlers):
            self.assertEqual(len(handlers),1)
            redirect=handlers[0]
            with self.assertRaisesRegex(ValueError,'redirects forbidden'):
                redirect.redirect_request(None,None,302,'Found',{},'https://evil.ts.net/')
            return RefuseOpener()
        with patch('scripts.portal_oidc_preflight.urllib.request.build_opener',side_effect=hook):
            with self.assertRaises(AssertionError):validate(ORIGIN,'https://kipnerter.com')

    def test_invalid_tailnet_host_grammar_denied(self):
        for issuer in ('https://.ts.net','https://a..ts.net','https://-idp.ts.net',
                       'https://idp-.ts.net','https://abc_.ts.net'):
            with self.subTest(issuer=issuer),self.assertRaises(ValueError):
                validate(issuer,'https://kipnerter.com',lambda *_: {})


if __name__ == "__main__":
    unittest.main()
