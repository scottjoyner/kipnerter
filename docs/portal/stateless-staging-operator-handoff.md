# Stateless fleet-chat staging qualification — operator handoff

This is a **no-write, owner-initiated** staging qualification path for
`kipnerter.com/chat` and its authenticated read-only fleet projections. The
spatial recovery workflow is separate: this path does **not** access or require
PostGIS/MinIO volumes, images, secrets, backup receipts or release approval SHA.

## Before attempting a real browser sign-in

Configure **staging GitHub environment secrets**, not plaintext workflow YAML,
for exactly these thirteen inputs:

- Tailnet CI identity: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`.
- Real tsidp OIDC: `TSIDP_ISSUER`, `TSIDP_CLIENT_ID`,
  `TSIDP_CLIENT_SECRET`, `NEXTAUTH_SECRET`.
- Signed operator allowlists: `KIPNERTER_ALLOWED_EMAILS`,
  `KIPNERTER_ALLOWED_TSIDP_SUBJECTS`.
- Private fleet monitor: `FLEET_MONITOR_BASE_URL`,
  `FLEET_MONITOR_TOKEN`, `KIPNERTER_GATEWAY_TOKEN`.
- Separate staging target: `KIPNERTER_DEPLOY_HOST`,
  `KIPNERTER_DEPLOY_USER`.

The tsidp issuer and private monitor must be HTTPS `.ts.net` root origins.
The staging host must be independently provisioned, have **only**
`tag:kipnerter-staging` (never also `tag:kipnerter-prod`),
and be reachable by an authorized Tailnet CI identity. The target login must
not be root. The operator must complete any legitimate Tailscale SSH
additional identity checks; do not bypass them by switching transports.

## Read-only checks

`scripts/portal_stateless_readiness.py --planned-sha <40-hex-commit>`
runs locally with environment variables and emits only missing **key names**,
invalid check names and permanent false release-authorization flags.

Once the workflow file is available on the repository's **default branch**,
an owner can dispatch `portal-stateless-staging-readiness.yml` with the exact
reviewed candidate SHA. The job checks the SHA's ancestry against the portal
development branch, the **stateless web/API-only Compose graph**, bounded
identity settings, uniquely staging-tagged Tailnet target, HTTPS OIDC metadata
and private observer origin. It does not issue SSH, start containers, expose
ports, write or read data backups, and never asserts real browser acceptance.
An absent staging tag or secret returns **NO-GO**, not a waiver.

## What permits a release (not yet achieved)

Actual staging deployment must separately prove authorized real browser
sign-in, denied subjects, expired/revoked sessions, private observer ACL,
exact live running source SHA, rollback, and explicit approved HTTPS ingress.
The public `kipnerter.com/chat` still requires an operator-authorized
reversible cutover. Source-side signed recovery evidence cannot substitute
for physical operation or independent custody; full spatial API rollout
remains behind its own PostGIS/MinIO recovery gates.
