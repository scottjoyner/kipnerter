# Kipnerter 1.7 — three-source release verification and HOLD

**Date:** 2026-10-19. This procedure proves reproducibility of source files, not readiness to change production state.

**Pinned inputs:** platform release branch exact SHA (the GitHub Actions commit), spatial backend `3490c05ce529b9d8775e9c99f358bb95481331f5`, and portal-compatible API gateway `88fcebbcbf951e966996c778321a6cfaaeae2298` (API PR #122).

## Completed read-only acceptance

[Hosted GitHub Actions run 39277298624](https://github.com/scottjoyner/kipnerter/actions/runs/39277298624) checked out all three exact SHAs using scoped source credentials with no persistence, ran the legacy and v2 negative controls, built two reproducible byte-identical v2 archives, verified SHA-256 at the receiving side, and staged files in an ephemeral private directory. The runner never contacted production or uploaded an artifact.

Version 2 requires `compose.gateway-031.yml`, `gateway-api/Dockerfile`, all three independent commit identifiers and the file-by-file SHA-256 manifest. Version 1 remains readable for the old two-repository release, but cannot accept a gateway v2 archive without an explicit gateway SHA. Tracked `.env.example` templates are excluded, not leaked in the release. The receiver writes `gateway_api_sha` into a private source receipt. The managed release preparer denies a v2 candidate unless its mode-0600 external environment supplies **exactly one** `KIPNERTER_GATEWAY_SOURCE_SHA` equal to the staged gateway SHA.

## Production release blockers, all still HOLD

1. The existing production host uses a legacy Compose layout rather than an independently identified managed `current` revision. Do not move, overwrite, or symlink `/opt/kipnerter` as part of a routine deployment.
2. Independently rehearsed, signed rollback evidence is needed for the existing Postgres and MinIO named volumes and the previous working web/API Caddy release. A file tree snapshot is not a database restore.
3. Production OIDC requires externally verified Tailscale Identity Provider issuance, restricted allowed email/subject lists, authentication cookies and browser login. The currently configured GitHub environment is missing its recorded prerequisites; never generate an unreviewed placeholder.
4. The API gateway needs its separately approved 0.3.1 bearer token and location-HMAC key. The v2 source/Compose adapter is opt-in only; the legacy production deployment workflow does not enable it.
5. The live chat composer is draft-only until owner-binding, admitted model provenance, execution receipts, quotas and independent fail-closed behavior are verified. No arbitrary Tailnet inference proxy is approved.
6. The signed iOS 1.7.0 IPA build `20261019134542` is already valid in **two internal TestFlight groups**. Preserve the existing app, Keychain, attachments and chat history until physical acceptance and independently recoverable prior-app rollback are witnessed.

**The next authorized deploy action is a staging and state-recovery rehearsal, not a production cutover.** Recheck exact Git source identity and public `/chat`, API `/health`, `/ready` and `/api/v1/release` before claiming any promotion.
