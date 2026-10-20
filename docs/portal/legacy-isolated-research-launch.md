# Isolated rollback launch harness — research-only, not legacy recovery

## Scope and result (October 20, 2026)

[Kipnerter issue #50](https://github.com/scottjoyner/kipnerter/issues/50)
blocks 1.7 cutover until **both** original production web and gateway
API images are present as verified executable rollback artifacts, or an
independently approved operationally equivalent replacement has passed
isolated web/API route/auth acceptance and actual rollback tests.
The original immutable OCI images remain missing from accessible caches.

`scripts/portal_legacy_isolated_candidate_smoke.py` is a strictly bounded
**research-only** disposable Docker rehearsal. It recognizes ONLY two
prequalified, locally cached immutable image IDs:

- `synthetic-loopback`: the independently cached, nonproduction Python
  3.12 slim image. This runs an ephemeral in-process Python HTTP fixture
  inside the container, never the Kipnerter application.
- `compat-031`: an unrelated preexisting API 0.3.1 compatibility
  candidate, **not** the historical production API. Uses its own
  original container command and probes localhost:8080.

Neither image is eligible for original legacy rollback promotion. The
script does not accept arbitrary image names, mutable tags, live
production images, passwords, registry URLs, host mounts, Docker volumes,
or release-approval arguments.

## Isolation gates

Both roles use `docker run --pull never --rm --network none`, no public
port mapping or forwarding, `--read-only`, drop all capabilities, deny
privilege escalation, `--pids-limit 64`, `--memory 384m`,
`--cpus 0.5`, synthetic 40-hex release identity, and only bounded
`/tmp`, `/run`, `/data` tmpfs. Specifically, `/data` overrides an
otherwise automatically created anonymous Docker volume declared in the
cached API image. This is critical: a read-only root filesystem does
*not* prevent Docker from honoring an image's default VOLUME directive.
Fail if `.Mounts` contains **anything**. Read back the exact network,
read-only mode, unpublished ports, image ID, running state, tmpfs
configuration, CPU/memory/PID limits, capabilities, privilege policy and
auto-remove status from the opened disposable container.

Probes run only via `docker exec` from inside the no-network container,
requesting **127.0.0.1:8080**; they do not publish any TCP socket to
the host or connect to production. Require 200 for `/health`,
`/ready`, `/api/v1`, `/api/v1/release`, and require 401 for
unauthenticated `/api/v1/control-plane/overview` and
`/api/v1/gateway/lmstudio/v1/models`. Bounded retries, no bearer keys,
no production DB/MinIO, and no agent dispatch.

The disposable test container is forcibly removed in a `finally`
block even if the service never starts. The harness performs a separate
`docker ps --all --filter name=... --format` read-back; missing cleanup
confirmation is a **hard HOLD**. No rollout or old-image import is
performed. Docker manages transient, local, research-only tmpfs and
container metadata; no application volumes are mounted.

## Physical x1-370 observations

**Synthetic positive control: PASS.** Using the locally cached
`python:3.12-slim` immutable image, the no-network synthetic HTTP
fixture satisfied all six expected health/deny checks, image identity
and isolation policy, and verified cleanup. The report is exactly
`SYNTHETIC_LOOPBACK_ISOLATION_PASS_NOT_LEGACY`, with
`actual_candidate_api_health_verified=false`,
`runnable_original_rollback_verified=false`, and
`safe_to_cutover=false`. Zero leftover disposable containers.

**Candidate application negative control: HOLD.** The cached
`kipnerter-api:031-portal-compat-20261019` image is not the original
production image. It is configured to run Uvicorn on port 8080 and
declares `VOLUME /data`. Initially, its implicit volume was detected
and rejected. After overriding `/data` with bounded tmpfs, an
independent read-back confirmed zero Docker mounts and full isolation.
The app's PID 1 Uvicorn process remained alive but never opened a
listener on localhost:8000/8080/3000 within the bounded observation
window, so health/auth contract acceptance **failed**. The harness
returned `HOLD` and removed the container; no relaxation of isolation
and no false success. This does not diagnose the application's internal
startup reason and is not evidence about historical production behavior.

To reproduce on an authorized x1-370 worker with these already cached
research images:

```bash
python3 scripts/portal_legacy_isolated_candidate_smoke.py \
  --research-role synthetic-loopback
python3 scripts/portal_legacy_isolated_candidate_smoke.py \
  --research-role compat-031
python3 -m unittest scripts.tests.test_portal_legacy_isolated_candidate_smoke -v
```

The actual candidate is expected to fail until separately resolved.
Twelve synthetic tests exercise policy and cleanup behavior. Test
reports never expose container logs, environment values or private
archive content.

## Next genuine executable rollback gate

The missing original web/API images, or independently approved derived
replacements, must first be retained in private operator custody with
their exact image configs and OCI layer/diffID verification. Then extend
the isolated rehearsal under separate authorization to test BOTH web
and API, old route/auth parity, process restarts and actual rollback
after simulated failure. This scaffold is **not** a production host
tester and will refuse historical image identities until a separately
reviewed and securely scoped acceptance mode exists.

Disk on x1 is near 95% utilization; do not trigger fresh Docker builds,
image pulls, exports or bulk archives from this recovery work without a
separate capacity preflight and approval.

Real PostgreSQL/MinIO recovery, independent high-water/custodian,
production Tailscale SSH authorization, OIDC and release approval
remain separate NO-GO gates. **No production traffic, service, secret,
container, database, object store or live volume was accessed or changed.**
