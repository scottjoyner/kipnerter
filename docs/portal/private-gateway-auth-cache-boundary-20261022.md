# Private gateway authentication-transition response headers

**October 22, 2026 — private preview security hardening.**

The observed Tailnet-only preview at `3a1b00e` served `/chat` with an explicit
no-store response, and the NextAuth unconfigured-provider route also carried
`Cache-Control: private, no-store`. By contrast, both the polling gateway
`/api/portal/nodes` and live-stream gateway `/api/portal/live` returned 503
without an explicit cache-control header while `tsidp` was unenrolled.
Because OIDC provider activation/revocation changes the meaning of HTTP 503,
401, and 200, **none of these user-scoped responses should be cached**.

This change introduces one `privateJson` response constructor used by the
polling and SSE gateway for:

- unrecognized portal section (404), identity not configured (503), expired
  or unapproved identity (401), missing upstream token (503), temporary
  upstream errors (502), and capacity denial (429);
- successful projected polling responses (200);
- SSE capacity denial retains `Retry-After: 15`, while successful SSE continues
  to send `private, no-store, no-transform` and now varies by cookie.

All private JSON responses include `Cache-Control: private, no-store,
max-age=0`, `Vary: Cookie`, `Pragma: no-cache`, and
`X-Content-Type-Options: nosniff`. They never add permissive CORS or public
cache directives. No authorization predicate, identity provider, session
lifetime, token, gateway upstream, or streaming capacity rule changes.

**Tests:** `node --test apps/web/tests/private-auth-cache.test.mjs`
uses synthetic HTTP responses and source-contract checks for every denial
path. `node --test apps/web/tests/*.test.mjs` covers the full frontend suite.
Hosted CI and a private-only runtime readback are required before promotion.
After deployment, verify HTTP status, cache-control, and protected fleet
routes under the still-unenrolled IdP. Do not interpret a green header test
as real browser authentication, IdP enrollment, write-fenced recovery, or
production release authority.

**Rollout rules:** Deploy at most the two already isolated web/API containers
on existing `x1-370` via the loopback-bound Tailnet preview. Preserve exact
previous images for rollback, verify the exact running release SHA and denial
headers, and perform a real image rollback/restore. Do not expose public
ports or change production infrastructure, storage, access policies, IdP
client registration or DigitalOcean resources. `release_gate=NO_GO` remains.
