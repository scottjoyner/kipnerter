# Research-only SIGKILL / clean restart rehearsal — no original-image rollback

## Scope

The original legacy Kipnerter web/API OCI images remain unavailable, and
issue #50 is P0/HOLD. The previously published offline OCI verifier and
isolated launch harness independently verify the structure and local
startup/auth of research images. This new experiment proves one additional,
separate property: after **an intentional process failure of an isolated,
nonproduction container**, a fresh container from the same pinned image
can be brought up and requalified, without changing production.

**This is a same-image fresh restart, NOT a rollback to an older image,
restoration of data, old-route equivalence, or release authorization.**

## Safety boundary

`scripts/portal_legacy_research_failure_recovery.py` delegates to the
strictly pinned research-only commands and no-network health/auth probe in
`portal_legacy_isolated_candidate_smoke.py`. Only two preexisting local
images are allowed:

- `synthetic-loopback`: cached `python:3.12-slim`, hosting an intentionally
  synthetic HTTP server on loopback.
- `compat-031`: cached `kipnerter-api:031-portal-compat-20261019` image,
  a **different** API compatibility build, not the original prod API.

Both are addressed by immutable image SHA-256. No production hostname,
SSH, DNS, public ingress or OCI registry is contacted. Neither workflow
downloads, builds, retags or imports any image.

Both the first and recovered containers must pass read-only isolation
attestation: `--network none`, `--read-only`, no port mappings,
zero Docker mounts (including no implicitly created `/data` volume),
exact bounded `/tmp`, `/run`, `/data` tmpfs, all capabilities dropped,
no-new-privileges, 384-MiB memory, 0.5 CPU, 64-PID limit, auto-remove,
synthetic-only location HMAC/bearer token, and the original immutable
research image ID.

HTTP requires 200 on health/ready/API root/release, 401 on unauthenticated
control-plane and gateway endpoints, and 200 on overview/nodes under
the **synthetic** bearer. Do not send production keys, tokens, routes or
data. Only localhost:8080 **inside** each no-network container is probed.
Full image ID and generated container ID/name are reverified before
the only destructive action:

```bash
docker kill --signal SIGKILL <newly-created, fully verified, disposable ID>
```

The script never kills a production name, host process, or a mutable
image tag. It waits until the first `--rm` container disappears, requires
a different full container ID for the fresh restart, and repeats isolation
and all HTTP/auth checks. In a `finally` block it force-removes both
generated disposable container names and independently confirms each
is absent. Failed qualification, missing SIGKILL acknowledgement,
stale image or container binding, wrong HTTP result, inability to
observe stop, or unverified cleanup are **HOLD**.

## Physical observed results on x1-370, October 20, 2026

Both preexisting, *research-only* image targets passed the complete
failure-and-restart sequence on x1-370 using the strict isolation
harness. Each returned:

- identical immutable image identity before/after, with distinct
  immutable container IDs;
- health/auth contract PASS before the SIGKILL and on the new container;
- pinned container identity verified before SIGKILL and stopped/removed
  evidence verified after;
- no published ports, no external network, zero persistent mounts;
- independent zero-leftover readback after cleanup.

Result: `RESEARCH_RESTART_AFTER_SIGKILL_PASS_NOT_LEGACY` with
`prior_production_image_rollback_verified=false`,
`database_or_object_store_restored=false`,
`original_historical_web_or_api_images_recovered=false`,
`production_modified=false`, and `safe_to_cutover=false`.

There is no evidence this same-image recovery actually uses or matches
the old deployed release, supports the old web routes, survives original
data migrations, or restores a PostgreSQL/MinIO state snapshot.

This test needs no downloaded/build image or temporary archive and is
appropriate for a capacity-constrained x1 worker (root filesystem was
about 95% utilized during the qualification).

## Commands and regression controls

```bash
python3 scripts/portal_legacy_research_failure_recovery.py \
  --research-role synthetic-loopback
python3 scripts/portal_legacy_research_failure_recovery.py \
  --research-role compat-031
python3 -m unittest scripts.tests.test_portal_legacy_research_failure_recovery -v
```

Twelve synthetic regression tests assert pre-kill binding and full
isolation, invalid images/nonces, injection refusal or wrong response,
wrong container ID, incomplete stop, second image launch failure,
failure of recovered bearer authentication, reused ID, denied cleanup,
and negative release claims. CI includes `scripts/tests` in the
`containers` job but the final published SHA must be qualified by an
actual exact-head GitHub Actions success before calling CI green.

## Missing production gates

Recover and privately verify **both** original historical web/API OCI
images (or a separately approved equivalent). Run a genuinely isolated
cross-image failed-upgrade/rollback rehearsal on them, checking legacy
route/auth and data compatibility. Independently restore Postgres and
MinIO backups with custody/high-water evidence, complete OIDC/human
operator authorizations, and only then propose ingress release.

The public `/chat` cutover remains blocked, not promoted by this
same-image research test. **No production modification was performed.**
