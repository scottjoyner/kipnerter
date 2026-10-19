# Kipnerter unified fleet portal (operator MVP)

The public URL `https://kipnerter.com/chat` must exist, but it **never** serves
private fleet telemetry to anonymous visitors. The login landing page is safe
without any configured identity provider. Only a validated, allowlisted OIDC
identity can access `/api/portal/{overview,nodes,models,traces}`.

## Trust boundaries and required identities

1. **Browser → Next.js:** Tailscale-backed OIDC via separately deployed
   [tsidp](https://tailscale.com/docs/features/tsidp), with HTTPS issuer, PKCE/
   OAuth state handled by NextAuth, verified email, and explicit
   `KIPNERTER_ALLOWED_EMAILS` and `KIPNERTER_ALLOWED_TSIDP_SUBJECTS` allowlists. `NEXTAUTH_SECRET` must be a fresh
   high-entropy secret (at least 32 chars). No browser localStorage credentials.
2. **Next.js → API:** server-side only, `http://api:8000`, using
   `KIPNERTER_GATEWAY_TOKEN`. All four portal endpoints reject missing/invalid
   credentials and return `Cache-Control: private, no-store`.
3. **API → private fleet:** explicit services configured via environment.
   AssistX read-only views come from **sanitized private observer snapshots**,
   not production-held general-purpose BasicAuth credentials. The fixed local
   publisher performs its requests inside the AssistX container, then strips
   every non-allowlisted field. Traces project **only** ID, outcome, count,
   and timing: no prompts, addresses, payloads, or tokens.
4. **Tailscale node presence:** optional `tailnet_observer.py` on a trusted
   fleet node reads `tailscale status --json` without sudo, strips addresses
   and identifiers other than hostnames, binds only loopback, requires a
   separate `FLEET_MONITOR_TOKEN`, and permits only GET `/health` and
   `/v1/nodes`. Publish to **authorized peers only** using Tailscale Serve and
   grants; **never Tailscale Funnel**. API uses
   `FLEET_MONITOR_BASE_URL` (the Serve URL) and the monitor token.
5. A service health response is not admission, a model name is not a loaded
   model, and an AssistX node record is not verified Tailscale presence.

## Provisioning order

- Verify deployed platform branch and an independent production rollback.
- Set up `tsidp` on your tailnet, register the application callback
  `https://kipnerter.com/api/auth/callback/tailscale`, enable appropriate
  browser reachability (Tailscale client or intentionally exposed IdP via its
  own supported secure mode), and verify identity signing, redirect URI, and
  claims. `tsidp` is experimental; pin its version.
- Configure `TSIDP_ISSUER`, `TSIDP_CLIENT_ID`, `TSIDP_CLIENT_SECRET`,
  `NEXTAUTH_SECRET`, `NEXTAUTH_URL=https://kipnerter.com`,
  `KIPNERTER_ALLOWED_EMAILS` and `KIPNERTER_ALLOWED_TSIDP_SUBJECTS` in GitHub deployment environment secrets.
  Without *all* values the portal fails closed and displays a setup notice.
- Enable the local scheduled AssistX snapshot publishers on x1-370.
  Neither the web nor the public API requires AssistX BasicAuth, and there is
  no credential-based fallback to privileged AssistX routes.
- On the trusted node run the observer with an independent 32+ char secret.
  Verify a denied unauthenticated GET, a permitted request with the observer
  token, and ACL denial from an unrelated node before configuring API access.
- Deploy to staging, validate access controls and SSE/event continuity before
  deploying to production. The portal has no direct agent execution endpoint.

## Read-only Hermes + OpenCode session integration

- The observer has a second bearer-protected `GET /v1/sessions` endpoint.
  It scans up to 5,000 local `fleet-agent-launcher` ledger entries with
  `O_NOFOLLOW`, file-size limits, job ID validation, and fail-closed parsing.
  It exports only IDs, agent type, status, requested model, timestamps, and
  verification/archival flags. No prompts, native session IDs, tokens, filesystem
  locations, full receipts, or raw agent traces are returned.
- The API exposes those projections under `/api/v1/control-plane/sessions`,
  and the authenticated web BFF under `/api/portal/sessions`.
- This first observer reports only launcher-managed sessions on the node hosting
  the observer; it is not yet a global multi-node OpenCode/Hermes inventory.
  `harvest_hold=true` means knowledge#173's archive hold is preserved.
- Run from the code checkout with `PYTHONPATH=apps/api
  python3 -m app.tailnet_observer`; the collector deliberately refuses
  non-loopback binding. Protect access over Tailscale Serve + scoped grants.

## Local observer operationalization (x1-370)

On October 17, 2026 the local read-only collector was installed on x1-370 with:

```bash
scripts/install-telemetry-observer.sh --install
systemctl --user is-active kipnerter-observer.service
```

The service uses the caller's **real** Unix home, not any isolated MCP HOME,
and installs under `~/.local/share/kipnerter-observer`. An independent,
unprinted bearer token is generated into `~/.config/kipnerter-observer/observer.env`
with mode `0600`; the unit binds only `127.0.0.1:8769`.

The host's user systemd manager rejects capability/mount namespace sandbox
directives with `218/CAPABILITIES`, so the compatible unit uses user-level
isolation, a loopback-only listener, and strict per-request authentication.
A stronger service-level sandbox should be tested independently, not
silently deployed when unsupported. The persistent observer does not imply
a public or tailnet endpoint: no Tailscale Serve/Funnel changes were made.

Verified with the active daemon: anonymous GET `/v1/nodes` returns 401;
token-authorized reads return 18 tailnet nodes and 11 local launcher jobs
without paths, IPs or raw trace data. For production access, first approve
the correct tailnet grants and explicitly publish a dedicated Serve path
for the read-only observer; do not reuse existing routes.

## Explicitly deferred

- Chat dispatch is **held**, not silently routed through unadmitted LM Studio
  or Router. Resume only after Auto-AssistX/Auto-Router demonstrates per-user
  identity, admitted loaded models, signed receipts, and failover fencing.
- Hermes, OpenCode, and Sophia currently expose health/configured status only.
  A dedicated user-scoped conversations, and shared trace
  identifiers need contract tests; no remote shell or command runner is
  exposed by this branch.
- Expand event streams beyond the existing bounded read-only metadata feed
  only after proving per-user authorization, source-specific replay limits,
  backpressure, revocation, and stronger trace lineage.
- Avoid storing browser tokens or redisplaying arbitrary trace payloads.

## Authenticated near-live activity feed

- The Next.js route `GET /api/portal/live` performs the same verified session
  and email allowlist check as other browser-to-API routes. If OIDC is unconfigured,
  anonymous users receive HTTP 503; missing authorization returns 401.
- The event stream polls ONLY the five fixed, bearer-protected read-only
  control-plane projections (overview, nodes, models, traces, sessions).
  Arbitrary paths and submitted commands are not accepted.
- Each stream lives at most two minutes, with a per-server-process limit of
  eight simultaneous connections, a 15-second observation interval, a seven-
  second upstream timeout, 128 KB per-response cap, and 15-second reconnect.
  Stale/unavailable sources fail to an explicit unavailable state rather
  than retaining a green indicator. No credential is ever sent to EventSource.
- The UI automatically falls back to bounded 30-second fetches when SSE fails.
  Source data remains *polled* and is not an upstream push subscription.
- Do not open source-side full trace payloads until user-bound authorization
  and retention controls are proven. The merged activity timeline intentionally
  labels uncorrelated launcher jobs separately from AssistX trace IDs.

## Tailnet HTTPS observer transport (October 18)

A dedicated Tailscale Serve route was added on **8448** to the existing
`x1-370` tailnet name, proxying its persistent loopback listener at 8769.
Tailscale reports `(tailnet only)`; no Funnel routes were added. Both
`/v1/nodes` and `/v1/sessions` returned HTTP 200 with the separate local
bearer token, and an anonymous HTTPS request returned HTTP 401.

To attach it to production, configure only on the private API container:

```text
FLEET_MONITOR_BASE_URL=https://x1-370.<tailnet>.ts.net:8448
FLEET_MONITOR_TOKEN=<a separately transferred secret, never checked in>
```

The Tailscale policy must first allow `tag:kipnerter-prod` to reach that
specific listener, not the whole node. The checked-in `infra/tailscale/policy.hujson`
is a **proposal**, not proof of what is currently applied. Validate reachability
from the *actual production identity* before enabling. Do not expose the
observer outside Tailscale, proxy it through Caddy, or place its secret in
`NEXT_PUBLIC_*` settings.

Even with a live collector, the public page cannot serve authenticated
telemetry until the production OIDC configuration has been verified,
the deployment SSH check completed, and the exact PR head released.

## October 18: audited local service observations

The optional observer now publishes `/v1/integrations` through the **same**
tailnet-only port 8448 and existing independent token. It performs these
fixed, read-only checks on `x1-370`:

- AssistX: loopback `GET /health` on port 8000.
- Sophia: active relay `GET /healthz` on port 8790. **Do not use the old
  port 8765** as proof the voice service is online: nothing is listening
  there on this host.
- Hermes: the known `hermes-gateway.service` active-state check.
- OpenCode: only launcher session history is available; process readiness
  remains **unverified** rather than claiming it is an always-on server.

The authenticated control-plane overview reports `local_status`,
`gateway_status`, and `source` separately. Healthy locally does not imply
the DigitalOcean API has authenticated reachability. The Sophia service
registry's public/private health path is now `/healthz`.

## Production identity and release preflight

Tailscale's experimental `tsidp` must be explicitly deployed on an admin-
approved tailnet node with HTTPS, durable state and the
`tailscale.com/cap/tsidp` admin capability. Register a confidential OIDC
client whose exact callback is:

`https://kipnerter.com/api/auth/callback/tailscale`

This requires the tailnet administrator to provision the IdP/client and the
deployment environment secrets. The portal's browser must be able to reach
the IdP on the tailnet; NextAuth on DigitalOcean must also reach discovery,
token and JWKS endpoints through its authorized Tailscale connection.

The GitHub production workflow now runs
`scripts/portal_oidc_preflight.py` after its tailnet join, validating
issuer discovery, HTTPS TLS, callback origin, and same-tailnet OIDC
authorization/token/JWKS URLs. The OIDC client credentials themselves
cannot be validated without a real login and must be verified separately.
The preflight does not call an OIDC API using the client secret.

Production no longer supplies the previously misleading default private
URLs for AssistX, Sophia or LM Studio. The workflow requires explicit
approved monitoring credentials and observer transport, then checks its
authenticated `overview`, `nodes`, `sessions` and `traces` projections.
It reads deployment secrets **as data, not by executing the .env file**.
All fields must come from the correct GitHub environment secrets and be
tested in staging before promotion. The frontend never receives them.

The public `/chat` route is still on a draft PR until an authorized staging
test, completed Tailscale SSH identity check, real OIDC login (and revocation)
and rehearsed rollback provide production acceptance evidence.


## Verified tsidp claim compatibility and subject authorization (October 18)

Source review of the current upstream tsidp token implementation found the
OIDC identity token includes signed `sub` and `email` claims derived from
Tailscale whois but **does not include `email_verified`**. The previous
NextAuth callback required that absent claim to equal `true`, silently
blocking all successful Tailscale sign-ins. The portal no longer assumes the
claim exists; it explicitly denies a present false claim and requires both
an exact signed-subject allowlist and an email allowlist.

The deployment now requires the additional
`KIPNERTER_ALLOWED_TSIDP_SUBJECTS` secret in GitHub's production
environment **and** passes it into the web container. The list contains
case-sensitive exact `sub` values taken from signed IdP test identities,
not a username or display name. Empty lists fail closed.

Both sign-in and each server-side NextAuth session callback check this paired
identity, and the web route/API require that verified pair. This resolves
tsidp token compatibility without granting email-only admission. Browser
sessions expire at most 15 minutes after sign-in, since JWT-only sessions
cannot guarantee immediate revocation or whois revalidation on each request.
A real IdP sign-in and revocation test is still required before release.

## Freshness and replay-sensitive displays

The production API rejects a signed-transport observer response if its declared
source does not match the requested read-only endpoint, its timezone-aware
observation timestamp is missing or unparsable, it is more than 90 seconds old,
or it is more than 10 seconds in the future. The adapter reports unavailable
rather than displaying an old successful observation as live. The response
also includes observation time for the UI so operators can distinguish a
fresh node sample from an old Hermes/OpenCode job.

This is a bounded freshness control, not signed checkpoints or tamper-proof
replay protection. Bearer-token integrity and Tailscale TLS/grants remain
prerequisites; do not call an observer reported response verified execution
or authoritative archival custody.

## October 18: genuine AssistX trace-index metadata feed

The x1-370 host now runs a separate scheduled **metadata-only** publisher,
`kipnerter-trace-publisher.timer` / `kipnerter-trace-publisher.service`,
which updates the protected file:

`~/.local/state/kipnerter-observer/traces.json`

The source publisher calls the **existing local** `assistx-api` container
through an allowlisted, fixed `GET /api/traces?limit=25&offset=0` URL.
The container already holds its own BasicAuth configuration and makes this
read-only request internally. No BasicAuth password is copied to the host,
passed to Tailscale Serve, or returned to the browser.

The publisher **cannot** be invoked through HTTP. Its host-side scheduled
process runs once roughly every 45 seconds and writes a single 0600 snapshot
with an atomic replacement (not an append-only transcript archive). Both
the publisher and the observer independently check snapshot structure,
ownership/private permissions, source identity, timestamps and bounded size.
Only five fields per record survive:
`correlation_id`, `outcome`, `events`, `last_ts_ms`, `duration_ms`.

The original `knowledge#173` raw-trace archival security hold remains
untouched. No new NAS writes, transcript harvests, model launches, or
Auto-AssistX deployment were performed. The source is the existing AssistX
Neo4j historical index, not direct real-time stream telemetry.

The tailnet-only observer now serves `GET /v1/traces` with the same separate
monitoring bearer token and HTTP 401 for unauthenticated clients. It returns
503 when the publisher has failed or a snapshot is older than 90 seconds.
The production API uses **only** this sanitized observer feed. The previous
  direct AssistX BasicAuth fallback is disabled and no privileged AssistX
  credential is passed to the production API container.

### Actual tested evidence

- 25 real trace-index records were returned over authenticated Tailscale HTTPS.
- The exact FastAPI `/api/v1/control-plane/traces` projection returned HTTP
  200, source `assistx_trace_index`, 25 records, and only the five allowed
  fields per record. Anonymous Tailscale HTTP requests returned 401.
- The latest execution event *in the sample* was **2026-10-16 13:28:41 UTC**,
  although the index snapshot itself was fresh on October 18.
- The API classifies that as `historical`, **not** `live`. It only claims
  live activity when an underlying event timestamp is at most five minutes
  old; a newly refreshed index alone cannot prove new executions.

### Operator recovery / checks

```bash
systemctl --user status kipnerter-observer.service
systemctl --user status kipnerter-trace-publisher.timer
systemctl --user status kipnerter-trace-publisher.service
# Safe, one-shot publisher refresh; no NAS harvest and no agent dispatch:
systemctl --user start kipnerter-trace-publisher.service
# Token-free HTTP test must deny:
curl -i https://x1-370.tailcb8954.ts.net:8448/v1/traces
```

To stop the metadata publishing without affecting the existing observer or
its other tailnet routes:

```bash
systemctl --user disable --now kipnerter-trace-publisher.timer
```

Old snapshots then expire naturally after 90 seconds. Do not remove the
separate subscriber authentication check, publish the observer with Funnel,
or expose the AssistX BasicAuth account directly to browsers.

## End-to-end smoke proof (2026-10-18)

`scripts/portal_e2e_smoke.py` is a self-contained, ephemeral integration
exercise that launches the **real** FastAPI control plane and built Next.js
portal on two free loopback-only ports. It generates a synthetic operator
identity, a short-lived signed NextAuth JWT, and an isolated server-to-server
API token. It **does not** create a real Tailscale login or a public endpoint.

The smoke checks the actual browser-facing paths and real NextAuth session
callback: anonymous BFF/SSE requests return 401; a signed but unallowlisted
subject also returns 401; expired signed cookies are rejected; an approved
synthetic subject can read only sanitized nodes, sessions and traces; the
unified SSE snapshot arrives with no browser-side gateway or observer token.
Every response is bounded and marked private/no-store.

CI runs this check in *no-upstream mode*: missing private sources produce
explicit `unavailable` records, not a fabricated healthy state. CI needs only
the repo, Node 22, and the pinned FastAPI Python requirements; no privileged
environment secrets or fleet connectivity.

An operator on `x1-370` may separately run the same check against the
**actual existing bearer-authenticated private observer**:

```bash
python3 scripts/portal_e2e_smoke.py --real-observer
```

This loads the *already-installed* observer credential from the Unix user's
private 0600 environment file, **never prints or persists it**, and uses
the dedicated tailnet-only Serve HTTPS endpoint. Real-data acceptance
requires live node presence, Hermes/OpenCode launcher receipts, and the
sanitized AssistX trace source. An empty/stale feed fails the test instead
of being presented as working.

Running either mode does not change Tailscale grants, Serve routing,
production services, GitHub environment secrets, AssistX admission, or
agent execution. It terminates both test servers after the run.

**Scope limit:** The synthetic signed-cookie test does not prove identity
provider discovery, OIDC authorization-code callback exchange, browser
reachability of `tsidp`, user-triggered logout, real-time revocation, or
deployment rollback. These require independently witnessed operator staging
acceptance before a public production rollout.

## October 18: strict public release and stream-capacity gates

The earlier deployment workflow could exhaust its public-health retry loop and
**fall through as successful even when /chat still returned 404**. Production
now calls `scripts/verify_portal_release.py`, which fails nonzero after all
attempts unless **all** checked public routes meet exact expected responses:

- Public `/chat`: HTTP 200, expected workspace marker, and a configured
  Tailscale sign-in link (not the setup-warning state).
- Public NextAuth `/api/auth/providers`: HTTP 200, valid JSON with the
  configured `tailscale` provider.
- Anonymous browser `/api/portal/live` and `/api/portal/traces`: HTTP 401
  (not 200 or identity-not-configured 503).
- Public API health, liveness, readiness: HTTP 200.
- Anonymous control-plane overview and traces: HTTP 401.
- Unexpected redirects, oversized responses, wrong status and unavailable
  endpoints all fail the release. Only fixed HTTPS origins are accepted.
  The check sends no operator cookie or private API credentials.

The preflight is deliberately distinct from the signed-in, remote production
API-to-observer checks and from human OIDC acceptance. It cannot validate an
OIDC authorization-code exchange or emergency rollback by itself.

`tests/test_verify_portal_release.py` reproduces a missing /chat route,
an unconfigured Tailscale provider, accidental anonymous telemetry exposure
and exhausted retries. The current live site correctly **fails** this gate.

The isolated `scripts/portal_e2e_smoke.py` also tests SSE resource behavior:
eight authorized browser streams connect simultaneously, a ninth must receive
HTTP 429, and a new connection must work after the clients close. This limit
is per Node server worker, not a globally coordinated cross-replica quota;
production concurrency/replica policy still requires staging validation.

## October 18: pre-deployment rollback integrity — required gate

Audit found that the old `scripts/rollback.sh` expected a Git checkout
inside `/opt/kipnerter`, while the deployment workflow explicitly excludes
every `.git` directory from its uploaded tarball. Git-based rollback was
therefore **not supported by the deployed application layout**.

The production workflow now stops *before writing any new release files* if
it cannot create and verify a private versioned backup of the currently
running application's local files. The exact `scripts/portal_release_backup.py`
from the checked-out commit is streamed to the already SSH-authorized
production user (not fetched from the public internet). It:

- Requires a real existing operator-owned application directory with
  `docker-compose.yml` and an existing private `.env`; refuses initial
  deployments without explicit migration/recovery planning.
- Denies symlinks, special files, unowned paths, oversized snapshots,
  insufficient disk space, and backup directories nested inside the app.
- Archives the prior application source and environment into
  `/home/kipnerter/.local/share/kipnerter-release-backups/`
  with mode-0700 directory and mode-0600 archive/checksum; it never
  prints secret values.
- Names each backup for the exact **new** 40-hex GitHub commit SHA
  (`pre-<new-sha>.tar.gz`), prevents overwriting a previous snapshot,
  validates archive members, and checks its SHA-256 checksum before upload.
- Supports `verify` and `rehearse` actions; `rehearse` restores the
  application to a separate **new** directory and never modifies the
  running deployment or starts containers.

Local fixture tests confirm backup/rehearsal roundtrips, prior-file
preservation, secret-file permissions, checksum-tampering rejection,
unversioned/missing deployment denial, and symlink rejection.

**Critical limitation:** This is an application-file recovery checkpoint,
**not yet a verified automatic production rollback**. The deploy flow still
extracts new files in place; Docker's named Postgres/MinIO volumes, schema
migrations, third-party identity state, and external credentials are **not**
captured by the archive. An operator-approved staging rehearsal of the
actual Compose rollback and a separate database/volume recovery plan are
mandatory before promotion. The legacy Git-based rollback script now refuses
tar-only deployments instead of misrepresenting them as recoverable.

Production SSH still requires Tailscale's interactive identity approval.
This workflow was not run against the production host, and no existing
production files, volumes, or identities were modified during this work.

## Streaming response limits and browser freshness

The BFF/SSE path now reads each fixed upstream JSON projection incrementally,
enforcing its 128 KB cap even when Content-Length is missing or false. Canceling
an SSE browser stream aborts its active upstream fetch and sleeping loop, and
the server closes slow-consuming streams instead of building an unlimited
snapshot backlog. Existing capacity remains eight streams per Node.js
process, with a two-minute hard lifetime. The one-process cap is not an
authenticated cross-replica per-user quota.

The browser treats a successful snapshot or valid polling result as a
time-limited observation. After 45 seconds without a valid replacement it
clears previous green badges and labels telemetry stale, rather than
presenting old health data as live. It invalidates earlier fallback fetches
when a newer SSE snapshot arrives, preventing an old response from replacing
newer evidence. React page state is never a replay or admission authority.

The bound-reader, abortable sleep, freshness, race prevention and previous
full-stack session/SSE checks run in CI. The live x1-370 observer still
distinguishes a fresh historical AssistX *index* from recent execution.


## October 18: local AssistX node and model inventory without privileged API credentials

Direct, authenticated read-only checks of the running AssistX container
confirmed that `GET /api/fleet/nodes` returned HTTP 200 with **zero nodes**
and `GET /api/fleet/models` returned HTTP 200 with **zero models**. This is
a **fresh, genuinely empty AssistX registry**, not a communication failure
and definitely not evidence that Tailscale fleet machines are absent.

A second local-only snapshot publisher,
`kipnerter-fleet-publisher.service` with
`kipnerter-fleet-publisher.timer`, now reads the two fixed endpoints
*inside the already-authorized local AssistX container*. Its BasicAuth
environment never leaves the container. It exports only an atomic, private
0600 `assistx-fleet.json` snapshot with:
- strict source and timestamp,
- at most 50 sanitized node names plus model-name lists and inflight counts,
- at most 50 sanitized model names and counts of reporting nodes.

The bearer-protected, tailnet-only observer offers `GET /v1/assistx-fleet`.
Requests without its independent token receive HTTP 401; invalid, tampered,
symlinked, oversized or older-than-90-second snapshots are rejected. The
public FastAPI control plane merges these projections with Tailscale online
state without using the old general-purpose `ASSISTX_MONITOR_USER/PASSWORD`
credentials. The production Compose and GitHub environment no longer pass
those credentials. An empty successful model response is labeled
`reported_empty`, distinct from `unavailable`.

The x1-370 physical acceptance sample yielded:

- Authenticated private `GET /v1/assistx-fleet`: HTTP 200 with **0 AssistX
  nodes, 0 AssistX models**; anonymous HTTP 401.
- Authenticated FastAPI `nodes`: HTTP 200 with **17 Tailscale-present nodes**,
  and separate `assistx_status=reported_empty`.
- Authenticated FastAPI `models`: HTTP 200 with
  `source=assistx_local_inventory`, `status=reported_empty` and 0 rows.
- Historical AssistX trace index remained at 25 metadata records, and the
  launcher receipt feed remained at 11 records.

Nothing has been submitted to Auto-Router, no model was loaded, no discovery
rescan was forced, no existing container was changed, and no new Tailscale
Serve/Funnel port was created. **Model discovery and actual loaded-model
attestation remain unresolved downstream gates**, independent of this
fresh-source telemetry milestone.

Safe local checks:

```bash
systemctl --user status kipnerter-fleet-publisher.timer
systemctl --user status kipnerter-fleet-publisher.service
curl -i https://x1-370.tailcb8954.ts.net:8448/v1/assistx-fleet
# Expected without token: HTTP 401
```

## October 18 evening: LM Studio native catalog reconciliation

Live read-only probes on x1-370 establish three distinct facts:

1. AssistX's currently registered fleet catalog reports **0 nodes and 0 models**.
2. LM Studio's standard OpenAI-compatible `GET /v1/models` responds 200 but
   reports **0 entries** at the same observation point.
3. LM Studio's native, fixed loopback `GET /api/v1/models` responds 200 and
   reports **10 locally available catalog items** (9 LLM, 1 embedding), each
   with an empty `loaded_instances` list at the observed time (**0
   runtime-reported instances**).

The portal now queries the native catalog **only inside x1-370** through the
already-running authenticated tailnet observer on HTTPS port 8448. New fixed
`GET /v1/runtime-catalog` forwards neither raw model paths nor the native
response body. It emits a tightly bounded summary: opaque SHA-256-derived
model ID, validated display name (or synthetic display ID), kind, count of
runtime-reported loaded instances and `independently_verified=false`.
There is no token, general-purpose native API proxy, model loading, tailnet
scanner, or new Serve/Funnel route. Anonymous requests still return 401.

The FastAPI `/api/v1/control-plane/models` projection now independently
reports `assistx_status` and `runtime_status`, and combines rows with a
source and specific state: `assistx_reported`, `catalog_available`, or
`runtime_reported_loaded`. No entry is called *admitted* or independently
verified. The frontend labels LM Studio entries as a **local catalog**, not
router admission. A native model with `loaded_instances>0` still requires
separate physical/process and user-bound execution witness checks.

Production release validation requires **both** authorized model sources to
return fresh metadata; a genuinely empty AssistX registry is accepted as
`reported_empty`, never silently substituted with runtime discovery.
The real-observer full-stack smoke test now requires the native model source.

These observations are not a production release: `kipnerter.com/chat` still
returns 404; Tailscale production SSH demands interactive identity approval;
real tsidp login and DB/volume rollback remain unproven.

## October 18 late: fixed-host fleet-runtime reconciliation

The private x1-370 host has six previously approved SSH aliases with
pinned host keys: `xwing`, `destroyer`, `lenovo`, `beelink`,
`deathstar`, and `optiplex`. The new metadata publisher probes **only**
these aliases, using noninteractive, host-key-verifying SSH with bounded
remote execution and an exact Python stdin program. It calls only fixed
`127.0.0.1` LM Studio native `GET /api/v1/models` and OpenAI-compatible
`GET /v1/models` endpoints, with redirects and inherited HTTP proxies
disabled. No credentials, process inventories, paths, model IDs, scripts
persisted on remote hosts, forced scans, model loads, or writes are involved.

`kipnerter-runtime-publisher.timer` periodically writes an atomic 0600
six-host count-only snapshot, which the existing token-protected Tailscale
observer exposes as **`GET /v1/fleet-runtime`**, without a new port or
Funnel. Missing endpoints are `unavailable` rather than `0 models`.
The snapshot independently enforces strict node allowlisting, schema, size,
Unix ownership/permissions, and 90-second freshness. It is not a secure
independently administered scientific witness or owner-bound execution proof.

Actual remote observations (October 18, 2026):

| Node | Native LM Studio catalog | OpenAI-listed models | Native-reported loaded instances |
| --- | ---: | ---: | ---: |
| Beelink | 11 | 11 | 1 |
| Optiplex | 25 | 25 | 0 |
| Lenovo | API 404 | 1 | Unavailable |
| Xwing | Unavailable | Unavailable | Unavailable |
| Destroyer | Unavailable | Unavailable | Unavailable |
| Deathstar | Unavailable | Unavailable | Unavailable |

These are *endpoint-reported state* observations at the sampling time, not
benchmark or executable admission. Beelink's one native-reported instance
requires separate process/residency and owner-bound evidence; Lenovo's one
OpenAI-compatible model row does not prove an active model. AssistX's central
registered model count remains 0 and must not be silently backfilled from
these independent sources. No worker is auto-loaded or promoted.

The FastAPI Models projection includes `fleet_runtime_status`, an observed
UTC timestamp and six count-only node rows. The Models screen renders a
separate fleet runtime table next to the independent x1-370 catalog and
AssistX entries. The authenticated full-stack smoke test checks the actual
private route and signed-in SSE projection, and rejects absent remote evidence.
Production release verification only checks the six-host telemetry receipt,
not that every host must have a runtime. Production SSH and tsidp login
remain independent release-blocking gates.
