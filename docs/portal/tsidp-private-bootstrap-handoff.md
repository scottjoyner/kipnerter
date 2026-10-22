# Kipnerter private tsidp bootstrap — operator handoff

This is a **non-public identity-provider bootstrap**, not authorization to deploy
or sign in to production. The running reference installation is on `x1-370`.
Its pinned source is `infra/tailscale/tsidp-preview.compose.yml`, and the
read-only observer is `scripts/portal_tsidp_bootstrap_readiness.py`.

The Compose project creates only one non-root container with a read-only root
filesystem, dropped capabilities, `no-new-privileges`, strict resource bounds,
no host ports, and a single dedicated persistent `/data` volume. It uses a
pinned official tsidp image digest; it cannot reuse the production database,
MinIO, or the currently deployed Kipnerter web/API volume names. It has no
embedded credentials and deliberately has `restart: no` until reviewed.

## Safe, read-only validation

```sh
# Offline shape validation; always returns NO_GO for real sign-in:
python3 scripts/portal_tsidp_bootstrap_readiness.py --offline

# On the bootstrap host only: check actual container identity, host config,
# state mount, online tag, and bounded OIDC discovery. Exit 3 until qualified.
python3 scripts/portal_tsidp_bootstrap_readiness.py

# Local/CI synthetic safety checks; never register or modify a Tailscale node.
python3 -m pytest -q scripts/tests/test_portal_tsidp_bootstrap_readiness.py
```

This script emits only boolean properties. It **never** prints enrollment URLs,
credentials, JWTs, machine keys, policy content, user emails or subject IDs.
Provider enrollment and discovery **do not** establish client registration,
real-browser login or production release authorization. After authorized
bootstrap, additionally run the strict private callback + discovery check in
`docs/portal/private-oidc-exact-issuer-preflight-20261021.md`. The issuer
must exactly match `kipnerter-idp-staging.tailcb8954.ts.net`; any substituted
Tailnet issuer or redirect is denied. Those always remain
`false` in this report.

## Explicit tailnet administrator actions (not automated)

1. Independently confirm the administrator's Tailnet and that the new identity
   provider should be authorized. Approve the existing **one-time interactive
   enrollment request** for hostname `kipnerter-idp-staging` and tag
   `tag:tsidp` only if the node is intended. Do not put the enrollment link or
   a `TS_AUTHKEY` in Git, logs, public issues, or chat.
2. Review Tailnet tag ownership, MagicDNS, HTTPS, and a narrow
   `tailscale.com/cap/tsidp` grant permitting *authorized admins* to access
   the IdP management UI. Never use a wildcard grant to all users simply to
   pass the bootstrap check. See the [official tsidp guide](https://tailscale.com/docs/features/tsidp).
3. Once the online IdP has a valid TLS certificate and well-known OIDC
   discovery, register a **staging-only** client with **exact** redirect URI
   `https://x1-370.tailcb8954.ts.net:8449/api/auth/callback/tailscale`.
   Confirm the issuer is exactly
   `https://kipnerter-idp-staging.tailcb8954.ts.net` before setting secrets.
4. Supply `TSIDP_ISSUER`, `TSIDP_CLIENT_ID`, `TSIDP_CLIENT_SECRET`,
   `NEXTAUTH_SECRET`, `KIPNERTER_ALLOWED_EMAILS` and
   `KIPNERTER_ALLOWED_TSIDP_SUBJECTS` using **approved secret custody** in
   the protected deployment environment. Never put real values in Compose,
   the repository, issue comments, or CI logs.
5. Perform the actual browser positive/negative/expiry/revocation tests from
   an eligible Tailnet device. Keep public Funnel, production DNS, production
   Caddy, SSH bypasses and production database cutover **disabled** until
   independently approved and reversible.

Note: Tailscale's tsidp image is experimental and may change behavior. Keep
the image digest pinned, review upgrades, and persist its signing/client state.
Provider enrollment is independent of PostgreSQL/MinIO restoration and does
not satisfy the full Kipnerter release recovery gate.

## Discovery redirect containment (read-only, October 21, 2026)

The bootstrap checker performs a **credential-free** TLS discovery read only
**after** the expected `kipnerter-idp-staging` peer is online and has the
reviewed `tag:tsidp` identity. Its request uses the exact private URL
`https://kipnerter-idp-staging.tailcb8954.ts.net/.well-known/openid-configuration`.
The request must never follow HTTP redirects, even if the redirected response
would subsequently fail origin verification. It rejects oversized discovery
metadata, JSON duplicate fields, changed response URLs, or missing TLS. No
client ID, client secret, administrator key or user credential is sent.

The fail-closed verification is covered by
`scripts/tests/test_portal_tsidp_bootstrap_readiness.py` using offline HTTP
fixtures for approved discovery, redirects, duplicate fields and oversized
responses. A successful network discovery proves only that the IdP is reachable
and serves valid metadata. **It cannot establish an OIDC client registration,
browser login, client revocation, or production deployment authority.** Those
require independent administrator action and real browser acceptance.
