# Private Tailscale OIDC preflight — exact issuer and callback binding

**Research/pre-deployment qualification, October 21, 2026.** This document
closes an implementation mismatch: the web runtime supported
`KIPNERTER_ENV=tailnet-preview`, but the Python OIDC discovery preflight had
only `production` and `staging` callback origins. The two runtime checks now
agree on the private origin **without granting permission to log in or deploy**.

## Exact private preview configuration

- Preview callback base: `https://x1-370.tailcb8954.ts.net:8449`
- Registered OIDC redirect URI must be **exactly**
  `https://x1-370.tailcb8954.ts.net:8449/api/auth/callback/tailscale`
- Sole acceptable private preview OIDC issuer:
  `https://kipnerter-idp-staging.tailcb8954.ts.net`
- Metadata discovery request goes to this issuer's
  `/.well-known/openid-configuration` path via HTTPS, with TLS validation.
- The Python preflight refuses HTTP redirects (including redirects to the same
  host), absent or overlong discovery documents, duplicate JSON fields,
  issuer mismatches, token/authorization/JWKS endpoints hosted elsewhere,
  malformed Tailnet names, credentials in URL, unexpected query/fragment/port.
- The NextAuth server-side runtime now also pins private
  `tailnet-preview` to the same **exact** issuer; merely being on a `ts.net`
  hostname is insufficient. Production and public staging continue to use
  their own exact callback origins and existing configurations.

Run this **only after independent Tailnet administrator enrollment**, HTTPS
certificate qualification and OIDC client approval:

```sh
KIPNERTER_ENV=tailnet-preview \
  NEXTAUTH_URL=https://x1-370.tailcb8954.ts.net:8449 \
  TSIDP_ISSUER=https://kipnerter-idp-staging.tailcb8954.ts.net \
  python3 -m scripts.portal_oidc_preflight

# Offline, no real OIDC client or production contact:
python3 -m pytest -q tests/test_portal_oidc_preflight.py
node --test apps/web/tests/tsidp-runtime-config.test.mjs
```

This preflight does not use client credentials or write to the IdP. It does not
register the OIDC client. Real client credentials, NextAuth secret and operator
email/subject allowlists must be provisioned through approved secret custody,
never embedded in Git, Compose, GitHub PR comments, or terminal logs.

A green *synthetic* issuer/discovery test cannot establish that the real
`tsidp` is enrolled, that its published TLS discovery is reachable, that its
registered OIDC client redirects correctly, or that positive/negative browser
logins and revocation behavior pass. The existing bootstrap report still
returns `tailnet_enrolled=false`, `oidc_client_registered=false`,
`browser_login_verified=false`, and `release_gate=NO_GO` until those
separate administrator actions are physically verified. No public route,
Tailscale ACL, production storage, cloud instance or API service is changed.
