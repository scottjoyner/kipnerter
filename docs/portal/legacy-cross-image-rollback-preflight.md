# Cross-version research preflight: refuse an unsafe fallback before disruption

**Historical executable rollback: HOLD.** The original production
web/API OCI artifacts are not recovered. This research does not reach
production networks, credentials, volumes, database, object store,
Caddy, DNS or live services.

## Physical October 20, 2026 route findings

All four API images were locally cached research candidates, not the
original prod image. Their immutable IDs were verified before the
isolated container observations.

| Research image | health, ready, API root | release route | control-plane overview/nodes | gateway models without token | Current portal compatible |
| --- | --- | --- | --- | --- | --- |
| compat-031 (321f8ee) | 200 | 200 | 401 anonymous / 200 synthetic bearer | 401 | YES, research-only |
| ios17-research (f8bc8c0) | 200 | 404 | 404 for both | 401 | NO |
| turns-research (b285614) | 200 | 404 | 404 for both | 401 | NO |
| recovery-research (ff8f3db) | 200 | 404 | 404 for both | 401 | NO |

These observations show why a single successful health check **cannot**
establish cross-version rollback safety for the current chat-facing
control-plane API. They are not evidence of authentic legacy behavior.

## Fail-closed executable research gate

Use `scripts/portal_legacy_cross_image_preflight.py` only for
explicitly allowlisted, locally cached, pinned, nonproduction image
pairs. Neither mutable image tags nor arbitrary image IDs or hosts
are accepted. The reused isolation contract requires network none,
no published ports, read-only rootfs, zero Docker mounts (including
no automatically created /data VOLUME), bounded tmpfs/memory/CPU/PIDs,
no-new-privileges, dropped capabilities, synthetic-only HMAC and
gateway bearer variables, HTTP 200 health/readiness/API root/release,
HTTP 401 anonymous protected endpoints and HTTP 200 synthetic-bearer
control-plane overview/nodes.

The order of work matters:
1. Check two expected immutable images are available and distinct.
2. **Prequalify and clean up the intended fallback before any SIGKILL.**
3. Only after that, launch and fully qualify the distinct upgrade image.
4. Re-bind its exact full container ID, immutable image ID and generated
   name before sending SIGKILL only to that newly generated disposable.
5. Observe disappearance, then launch a different new fallback
   container, and repeat security and health acceptance.
6. Force-clean up all generated containers and independently read back
   absence. Any ambiguous cleanup or failed acceptance means HOLD.

## Physical research controls

- **Synthetic positive mechanics:** pinned compat-031 API upgrade
  candidate -> pinned Python synthetic HTTP fixture as fallback:
  fallback preflight PASS, API preflight PASS, targeted disposable API
  SIGKILL verified, fresh Python fixture fallback PASS, zero leftovers.
  The synthetic fixture is **not an application or production fallback**.
  The output always sets `operational_equivalence_verified=false` and
  `safe_to_cutover=false`.
- **Actual candidate compatibility negative:** compat-031 upgrade ->
  ios17-research rollback candidate: failed the route preflight and
  returned HOLD (exit 2) **before any SIGKILL**. Separate isolated
  observations confirmed that turns-research and recovery-research also
  lack the release/control-plane routes. Zero test containers remain.
- No image pulled, built, exported or imported. No stateful backup or
  production host accessed.

Reproduce from the approved research worker with cached images only:

~~~bash
python3 scripts/portal_legacy_cross_image_preflight.py \
    --upgrade-role compat-031 --fallback-role synthetic-loopback
# Positive fixture mechanics only, never historical rollback.

python3 scripts/portal_legacy_cross_image_preflight.py \
    --upgrade-role compat-031 --fallback-role ios17-research
# Expected HOLD exit 2 before injection.

python3 -m unittest scripts.tests.test_portal_legacy_cross_image_preflight -v
~~~

Thirteen synthetic fail-closed tests cover invalid pairs/IDs, historical
route 404s, unexpected mounts, unauthenticated or stale credentials,
mismatched container identity, wrong SIGKILL acknowledgement, failure
to disappear, failed fresh fallback, reused identity and missing cleanup.

## Missing production release gates

Issue #50 remains P0. Identify approved runnable artifacts for **both**
historical web and API; prove old route/browser auth parity and real
cross-version rollback, then independent PostgreSQL/MinIO restores,
witness custody and user-approved production identity/security checks.
The release gate remains HOLD, and public /chat is not promoted.
Disk on x1 is near 95% used; avoid downloads and bulk image exports.
