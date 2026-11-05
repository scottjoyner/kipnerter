# Dedicated LFM3 service manifests

These files mirror the rootless units installed and tested on the fleet on
November 4, 2026. Do not replace existing unit files blindly: compare their
current contents, exact host identity, backend build, and model paths first.

- The R9700 bridge exposes only its **pre-existing API-key-protected** local
  research listener over Tailscale. Stopping this bridge never stops that model.
- The RX 480 Vulkan server is independent, single-slot and admitted only when
  VRAM and host-memory preflights pass.
- OptiPlex is CPU-only, deliberately lower priority and memory/CPU bounded.
- Dedicated token files must be created through an authorized secret provisioning
  workflow, under the specified home directory at permission mode 0600.
  Never commit or print their contents.

For the two preflight scripts, install their contents at the matching paths
under `~/.local/libexec/kipnerter/` with mode 0750. Compare unit files against
the live `~/.config/systemd/user/` versions before any replacement. Run
`systemctl --user daemon-reload` only after operator review. Each unit is
independently enabled, inspected, and reversed with:

```sh
systemctl --user status kipnerter-lfm3-rx480.service
systemctl --user disable --now kipnerter-lfm3-rx480.service
```

Substitute the correct unit for the particular node; never kill generic
inference servers or modify x1-370. See
[`docs/operations/lfm3-fleet-admission.md`](../../docs/operations/lfm3-fleet-admission.md)
for verified health, per-node gateway config and remaining rollout gates.

## Private gateway acceptance and approved secret mounts

The **verified worker-local keys already exist** on R9700, RX 480, and
OptiPlex. The public web gateway remains unprovisioned. Do not copy those
keys with chat, shell command output, GitHub, iOS, or Docker environment
variables. An earlier credential-transfer operation was blocked and must
not be bypassed.

This directory includes two deploy-time aids that are safe to review and
test **without actual credentials**:

- `compose.staging.yml`: an *unapplied* template for a **second**
  localhost-only staging candidate (`127.0.0.1:3354`). Its three
  exact-model workers have separate credential **references**. It mounts
  an explicitly provisioned private directory at
  `/run/secrets/kipnerter-lfm3` as read-only and refuses to silently
  create a missing host directory. No public Caddy route is specified.
- `gateway-acceptance.mjs`: a fail-closed, one-generation acceptance
  gate. It checks the localhost home page, pre-inference HTTP 413 handling,
  and *only metadata* (regular file / mode / size) for each secret mount.
  It does **not** read or print token values. If any mount is missing,
  the result is `HOLD` and no inference is requested. After approved
  provisioning, it requires a real `LFM3-1.7B` HTTP 200 response with
  a nonempty correct arithmetic answer. An HTTP 503 or bad model is
  not considered release-ready.

A production-host **read-only Compose syntax check** passed with:
`KIPNERTER_LFM3_STAGE_IMAGE=kipnerter-lfm3-staging:1f2f788`,
`KIPNERTER_LFM3_SECRET_DIR=/nonexistent/lfm3-staging-secrets`, and
`docker compose -f - config --quiet`. This only parses the plan; no
container, directory, mount, or secret was created.

For a future approved operator change, first have the designated
secrets-management process provision the three root-owned 0400/0600
regular key files into a locked-down directory on the Docker host. Review
that private directory's ownership, deployment ACLs, canonical model
aliases, existing Caddy ingress and image SHA **before** issuing a new
staging `docker compose up` from an authorized checkout. Leave the
existing localhost candidate running until the new one passes the
gateway-acceptance check, and **do not expose either staging listener**.

The production droplet does not currently have a host-level `node`
command, but its web container includes Node.js. The acceptance module
can be run from an authorized Node environment with access to the
loopback stage URL and Docker metadata inspection, or invoked through
a reviewed container-local harness. The current staging check was
run without copying any key material and returned:

```json
{"decision":"HOLD","gate":"protected-model-secrets","workerMounts":{"r9700":"missing","rx480":"missing","optiplex":"missing"}}
```

**Release remains HOLD** until an approved secret mount, a real
authenticated request through the staged Next.js route, and independent
edge/global abuse-control verification all pass. Only then review public
Caddy promotion and the signed iOS/TestFlight gate. The iOS app uses
`https://kipnerter.com/api/chat/completions` and must never contain
Tailnet credentials or individual worker addresses.

## Public edge phase-one cutover candidate — deliberately unapplied

A read-only production Caddy inspection on November 4 found that the
current Caddyfile proxies `kipnerter.com`, `www.kipnerter.com`, and
`preview.kipnerter.com` to the existing public web container and has
**no explicit LFM3 chat route**. It also lacks a shared rate-limiting
directive and request-body cap. The running image is **Caddy 2.11.4**;
its listed modules include `http.handlers.request_body` but no
`http.handlers.rate_limit`. Therefore do **not** assume a Caddy
`rate_limit` directive will work on the deployed binary.

The file `caddy.phase1.candidate.Caddyfile` is an **unapplied** full
candidate preserving the existing public, spatial API, artifacts and
admin backends. It routes **only canonical-host POST**
`https://kipnerter.com/api/chat/completions` through the separate
Caddy-namespace loopback rate-limiter candidate to the future provisioned
LFM3 gateway. The operator research endpoint remains on the existing
site and unavailable until NextAuth and its own security gates pass.
It enforces an 8 KB request-body cap and overwrites untrusted
forwarded-IP headers before the Next.js process-local rate limiter.

The actual production Caddy binary ran a `caddy validate --config
/dev/stdin --adapter caddyfile` **without installing/reloading the
candidate** and returned `Valid configuration`. This proves syntax
and module compatibility only; **it does not prove** public request
routing, shared/global abuse protection or authenticated inference.
Tests in `apps/web/tests/lfm3-caddy-cutover.test.mjs` ensure that the
candidate preserves its restricted host/method/path and fallback.

The cutover remains **HOLD** until all of the following are physically
verified and recorded together: approved protected key mounts on a
staged gateway; an authenticated LFM3 completion via that gateway;
shared/edge-wide abuse controls appropriate for the deployment;
the candidate's IP-header semantics and reverse proxy's connectivity;
an exact-head Docker image and signed acceptance record; an immediately
available rollback to the unchanged public site; then authorized Caddy
promotion. Merely loading model catalogs or returning `/health 200`
is insufficient evidence. The new iOS default must not be TestFlight
distributed while public chat is HTTP 404 or 503.

The candidate deliberately introduces **no** `rate_limit` directive
since the host lacks that Caddy plugin. Its absence is an explicit
release blocker requiring a reviewed edge limiter/proxy implementation
(or a suitable shared backend limiter) rather than a hidden assumption.

## Unapplied shared edge limiter sidecar (November 4)

A deployment candidate now exists under `deploy/lfm3/edge/`:

- `nginx.conf`: a **single shared-memory Nginx limiter** providing a
  6 requests/minute per-client bucket (burst 2), a 30 requests/minute
  global bucket (burst 5), and a two-active-request concurrency cap.
  The gateway's effective per-client quota remains the stricter of
  these edge quotas and its process-local guard. The limiter returns
  HTTP 429 on saturation; only POST on the canonical chat route can
  be forwarded; unrelated routes return 404. Access logs are disabled.
- `compose.edge-candidate.yml`: an **unapplied** Docker Compose plan.
  Uses a mandatory operator-approved immutable SHA256 image reference,
  runs as uid/gid 101, read-only root filesystem, no added privileges,
  no published ports, and shares the existing Caddy container network
  namespace with a listener on **127.0.0.1:8094**.
- `verify-isolated-limiter.sh`: **optional offline acceptance test**
  for a separately approved image already present in the local Docker
  image cache. It refuses an unpinned/unavailable image (no pull),
  runs a temporary `--network none` container with an intentionally
  nonexistent model upstream, validates Nginx syntax and tests 404,
  405, 502 and rate-limit 429. No secrets, models, public routes or
  DNS/external network are involved.

The matching **unapplied** `caddy.phase1.candidate.Caddyfile`
would proxy only the canonical POST chat route from Caddy to its own
namespace's loopback `127.0.0.1:8094`, overwriting `X-Real-IP` and
`X-Forwarded-For` with Caddy's observed remote host. Requests then
pass the centralized limiter to the separately provisioned LFM3
gateway. Other public Caddy routes retain their existing backends.

The live Caddy 2.11.4 binary validated this *candidate* Caddyfile
via stdin, and `docker compose -f - config --quiet` parsed the
sidecar manifest. The registry subsequently advertised an official
Nginx Alpine **candidate OCI image-index digest** of
`sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949`
(linux/amd64 variant, 1.30.6-alpine). That digest-pinned image was
cached on the production host for an **offline temporary-container smoke
test**. The test ran `nginx -t` and verified that unrelated URLs
return 404, non-POST completions return 405, and repeated completions
return a 429 from the shared rate-limit zone. The intentionally absent
upstream produced 502 *before* rate limiting was triggered. The test
reported `OFFLINE_EDGE_ACCEPTED`, and the temporary container was
removed. No gateway/model, public Caddy route, or credential was used.
This is **stronger than syntax-only validation**, but the image
provenance/approval, correct client IP behind Caddy, rate limits behind
live TLS, and lifecycle when Caddy is recreated **remain unverified**.
The image's cache presence does not authorize its production use.

**Activation order** remains strictly HOLD until an authorized owner
records: (1) immutable and verified Nginx image digest plus offline
smoke test, (2) approved protected model-key mounts and authenticated
staged LFM3 completion, (3) Caddy namespace and sidecar lifecycle
review, (4) global and per-client rate-limit acceptance through the
edge, (5) prepared rollback and authorized public routing switch,
(6) live public HTTPS acceptance, then (7) signed iOS/TestFlight
approval. In particular, a configured 429 limiter cannot compensate
for missing gateway credentials or an HTTP 404 public chat route.

## Offline Caddy + Nginx chain acceptance — November 4, 2026

The release branch now includes `edge/verify-isolated-caddy-chain.sh`,
a second offline test that runs the **actual cached Caddy image**
(current public container image ID
`sha256:df7f1c2fb114453b951de51a98efc010db1655a92c2e86be6706714e2417a78d`)
and the above digest-pinned official Nginx image in **throwaway containers
sharing one network-disabled namespace**. The HTTP-only Caddy test
listener faithfully mirrors the canonical host/path/method matcher,
8 KB Caddy request-body policy, and IP-header sanitization from the
unapplied phase-one candidate. The real Nginx config is only changed
for the test to point its backend at a nonexistent local port, where
HTTP 502 is the expected pre-limit response. Neither production Caddy
nor the model gateway is contacted.

The latest executed offline acceptance returned:

- Wrong hostname `preview.kipnerter.com`: `404`, not routed.
- Five canonical requests forged **five different**
  `X-Real-IP` and `X-Forwarded-For` addresses; first three
  produced `502`, fourth/fifth `429`. Because Nginx's global bucket
  would not block as early as request four, this demonstrates that
  Caddy correctly replaced the spoofed client-IP headers and the
  **per-client** bucket grouped all five by observed source.
- Direct requests to the isolated Nginx listener with five **distinct
  synthetic** client keys then produced `502, 502, 502, 502, 429`.
  This demonstrates that the independent **global shared-memory**
  request bucket rejected traffic across distinct client identities.
- The command printed
  `PASS: isolated Caddy->Nginx canonical host, spoof-resistant per-client
  429 and global 429`, then cleaned up its test containers.

The Caddy test container uses default file-capability execution because
the installed official Caddy binary cannot execute with both
`--cap-drop ALL` and `no-new-privileges`. It still has
`--network none`, no exposed host port, read-only rootfs, bounded
memory/CPU, and no mounted secrets. The Nginx test container remains
nonroot with all capabilities dropped. The production sidecar candidate
itself is unchanged.

**Scope of evidence:** Caddy-to-limiter request routing and basic
forwarded-IP spoof protection passed **in an isolated HTTP test**.
This does not prove correct behavior behind the actual public TLS
entry point, load-balancer/CDN client identity, multiple Caddy
replicas, production concurrency, or availability during container
restarts. Exact-image provenance/approval, safe lifecycle,
approved gateway key mounts and authenticated staging completion are
still required before any public cutover or TestFlight release.

## First operational MVP: a real RX480-only authenticated web gateway

A new **unapplied** `compose.staging.rx480.yml` provides a constrained
localhost-only (`127.0.0.1:3355`) Next.js gateway with **one** explicitly
admitted real LFM3 model worker, Deathstar/RX480. Unlike the three-worker
candidate, this can be staged with a single, separately provisioned protected
`rx480.key` secret. It uses the actual `/api/chat/completions` route, not a
mock server or fallback response. Its static model alias is
`lfm3-1.7b-rx480`, and it does not require the other two workers to be
available.

The new operator acceptance command, when the isolated service has been
provisioned and started by the authorized host deployment mechanism, is:

```sh
node deploy/lfm3/gateway-acceptance.mjs \
  kipnerter-lfm3-stage-rx480 http://127.0.0.1:3355 --rx480-only
```

This command verifies the live home route, too-large rejection, protected
RX480 key-file metadata *without ever reading or printing the key*, and a
**real authenticated generation** returning LFM3-1.7B with the correct
nonempty arithmetic reply. A missing key, network issue, HTTP 503 or invalid
model reply is HOLD/FAIL, **never simulated success**. The previous default
three-worker acceptance remains unchanged. The RX480-only option is accepted
only for the exact `kipnerter-lfm3-stage-rx480` staging container; operator
cannot use it to bypass the full staging checks.

This is implementation delivered in the repository, not proof of an actual
deployment. The image must be built and pinned from accepted source, the
RX480 key must be provisioned through the approved secret manager, and the
Docker network / Tailnet reachability / live authenticated response must all
be checked. Do not open public ingress or ship TestFlight before separately
passing public HTTPS, abuse controls, rollback and release gates.
