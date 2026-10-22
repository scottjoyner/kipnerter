# Fail-closed OIDC configuration in the browser runtime

`apps/web/lib/tsidp-config.mjs` verifies the deployed NextAuth settings
at application startup in addition to the existing operator preflight:

- Issuer is a root `https://<host>.<tailnet>.ts.net` origin, with no userinfo,
  query, fragment, unexpected port or URL path.
- Only the exact selected `production` or `staging` callback origin is
  accepted; either environment incorrectly pointing at the other is denied.
- OIDC client ID/secret and JWT secret are present, bounded, and contain no
  CR/LF/NUL; the JWT secret must contain at least 32 characters.
- Both email and signed tsidp subject allowlists are nonempty, properly
  formatted, unique, and have at most 32 entries. Email entries are lowercase.
- Invalid configuration results in an HTTP 503 no-store provider response and
  no authenticated fleet reads. It does not fall back to anonymous access.

This is a **local configuration check**, not a proof that a live tsidp server
exists, has valid TLS certificates, or issues the exact signed subject
claims. Tests use synthetic non-secret identities only. Actual browser
sign-in, rejection, expiry and revocation require a separately approved
private tailnet identity provider and staging DNS/TLS. This change adds
no token generation, Docker deployment, public routing or agent execution.

The tailnet admin must still configure the experimental tsidp server,
grant its admin capability only to approved admins, register an OIDC client,
pin the redirect URI and store the credentials in the protected environment.
Until those operator tasks are complete, public chat release remains HOLD.
