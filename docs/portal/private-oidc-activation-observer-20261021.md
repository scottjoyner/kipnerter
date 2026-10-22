# Kipnerter private IdP activation — read-only operator checkpoint

**October 21, 2026.** Source: existing PR #77; no new cloud services,
production changes, IdP enrollment, client registration, secrets, browser
sessions, or API writes are performed by this observer.

The operator should be able to distinguish a healthy **private chat landing
page** from a real authenticated fleet portal. The landing page can return
HTTP 200 while `/api/auth/providers` and `/api/portal/nodes` return 503,
correctly denying unconfigured authentication. A successful **synthetic**
session smoke test does not prove a real Tailnet browser login.

## Safe one-shot checks on x1-370

```sh
# Safe default: no Docker or network calls, fails closed.
python3 -m scripts.portal_private_oidc_activation_readonly

# Explicit observer; only already-approved private GET routes and existing
# read-only Docker/Tailscale enrollment+discovery checker may run.
python3 -m scripts.portal_private_oidc_activation_readonly --execute

# Local negative-control tests (no live network or storage):
python3 -m pytest -q scripts/tests/test_portal_private_oidc_activation_readonly.py
```

The checker pins the known private origin
`https://x1-370.tailcb8954.ts.net:8449` and already-qualified preview web
revision `3a1b00ea76a3ec968f4caca282a6909670941216`. It refuses HTTP
redirects, unexpected release JSON, wrong revision, denied chat page,
unexpected authentication exposure, or a non-isolated bootstrap. It makes no
request to a public service, private credential endpoint, or production
storage. It prints only bounded HTTP status codes and boolean readiness
flags. It does not print container environment values, secrets, browser
cookies, email addresses, or enrollment auth tokens.

The first outstanding prerequisite is exposed as `next_action`, but
`client_registration_independently_verified`, `real_browser_login_verified`,
`revocation_proven`, `independent_recovery_custody` and `safe_to_cutover` are
**always false**. Even with a reachable IdP, this observer cannot witness
approved client registration or a real browser session. Production release
is therefore **always `NO_GO`**.

## Authorized administrator handoff

Per [Tailscale's tsidp documentation](https://tailscale.com/docs/features/tsidp),
the Tailnet's Owner, Admin, or Network admin must verify MagicDNS and HTTPS,
review the `tag:tsidp` ownership and narrowly scoped
`tailscale.com/cap/tsidp` client-management capability, and approve the
already running isolated `kipnerter-idp-staging` node. This must not be
accomplished by bypassing Tailscale's interactive SSH checks or embedding
an auth key in Git/Compose. After the node joins, open the private IdP
admin UI as an approved administrator and **create an OIDC client** with
exact redirect URI:

`https://x1-370.tailcb8954.ts.net:8449/api/auth/callback/tailscale`

The **only** approved private issuer is
`https://kipnerter-idp-staging.tailcb8954.ts.net`. Store the generated client
ID/secret and separate NextAuth/session secret through approved private
secret custody, never in logs or PR comments; configure explicit approved
user email+subject lists. Recheck fixed OIDC discovery with
`scripts/portal_oidc_preflight.py`, then perform actual authorized browser
login, unauthorized-user rejection, expiration and revocation tests. The
separate PostgreSQL/MinIO write-fenced consistent backup + independent
custody remains a different production cutover gate.

**No observation, localhost redirect, synthetic token or manually set
boolean qualifies a real OIDC login.** All drafts remain unmerged until
independent review/approval.
