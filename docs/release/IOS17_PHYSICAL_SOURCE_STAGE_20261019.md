# Kipnerter 1.7 production SOURCE staging — one-shot approval

**Only authorizes copying three Git-verified source trees into the existing nonroot deployment account's private data directory on the uniquely tagged production host.** It does not authorize changes to running web/API/Caddy/worker services, PostgreSQL, MinIO, OAuth, location ingest, model routing, beta distribution or an App Store release.

Exact source inputs:
- Portal release Git commit: the owner-approved workflow run's immutable `github.sha`.
- Spatial backend: `3490c05ce529b9d8775e9c99f358bb95481331f5`.
- Read-only portal-compatible gateway 0.3.1: `88fcebbcbf951e966996c778321a6cfaaeae2298`.

No credentials or `.env` files are bundled. Two deterministic source archives must match; the same exact Git-controlled verifier checks every file's SHA-256 again after the archive reaches the remote host. Destination is private `/home/kipnerter/.local/state/kipnerter-release/verified/<portal SHA>`; already existing source files cannot be overwritten.

**This does not authorize cutover.** Production remains HOLD until signed Postgres/MinIO restoration, approved transition from legacy Compose layout, production OIDC/allowlists, gateway credentials, and a staged browser health test all pass. Existing internal TestFlight 1.7.0 build is unrelated and must not be rebuilt or reassigned.
