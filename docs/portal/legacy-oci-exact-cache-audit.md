# Legacy OCI exact-image cache search — 2026-10-20

## Question

Do **exact** immutable old `kipnerter-web-1` and `kipnerter-api-1`
Docker image IDs, pinned in production launch receipts, exist on any
already authorized and reachable non-production fleet Docker daemon?
This is about the existence of original recoverable OCI images, not
whether a newer API source or rootfs tar *looks similar*.

The two identifiers were preserved by the owner-private legacy launch
receipt verification run
[39432194703](https://github.com/scottjoyner/kipnerter/actions/runs/39432194703);
that run found intact rootfs exports but **no executable OCI rollback**.

## Method

`scripts/portal_legacy_oci_fleet_cache_audit.py` queries a fixed,
allowlisted set of six known fleet aliases over SSH using
`BatchMode=yes`, `StrictHostKeyChecking=yes`, no forwarding,
no TTY and a short timeout. Its remote command only calls
`docker info --format '{{.ServerVersion}}'` and
`docker image inspect --format '{{.Id}}'` with the *exact two IDs*.
All raw SSH stderr, credentials, container config and environment are
suppressed. No mutable tags, image pulls, layers, credentials, volumes,
containers, Docker socket proxy or production SSH connection are used.

The scanner MUST distinguish:
- `EXACT_ABSENT`: reachable, confirmed accessible Docker daemon explicitly
  failed to resolve the given image ID.
- `DOCKER_INACCESSIBLE`: SSH reached the host, but Docker daemon CLI or
  access was not available. **Not evidence of absence.**
- `SSH_UNAVAILABLE`: authentication, network, hostname or timeout prevented
  proof. **Not evidence of absence.**
- `UNTRUSTED_RESPONSE`: malformed/ambiguous output. **Not evidence of absence.**
- `EXACT_PRESENT`: exact `docker image inspect` readback matches the pinned
  original ID. **Still not proof an image will run or rollback.**

No production host is in the script's allowlist; do not work around
an additional Tailscale identity challenge.

## Physical results

On October 20, 2026, Fleet Commander ran the same exact-id checks on
`x1-370` locally and the six allowlisted remote aliases.

| Machine | Docker evidence | Legacy API ID | Legacy web ID |
| --- | --- | --- | --- |
| x1-370 (local) | Docker accessible | exact image absent | exact image absent |
| Destroyer | Docker accessible | exact image absent | exact image absent |
| Xwing | Docker accessible | exact image absent | exact image absent |
| Lenovo | Docker inaccessible | unknown | unknown |
| Beelink Ryzen mini-PC | Docker inaccessible | unknown | unknown |
| Deathstar XPS 8920 | SSH unavailable, Tailscale additional identity check | unknown | unknown |
| Optiplex 9030 AIO | SSH unavailable, Tailscale additional identity check | unknown | unknown |
| Production | **not probed** | no new evidence | no new evidence |

Note: a read-only production verification run already established that
the exact original web/API image IDs could not be resolved from its local
image cache; original containers remain running. That result is separate
from this non-production fleet check.

For authorized reproduction from x1:

```sh
python3 scripts/portal_legacy_oci_fleet_cache_audit.py
python3 -m unittest scripts.tests.test_portal_legacy_oci_fleet_cache_audit -v
```

The only script output is bounded role/host classification, image-hit
labels (if any), and explicit refusal of release claims. Seven additional
negative/positive tests cover host allowlisting, full-hash matching, SSH
denial, Docker unavailability, malformed/untrusted host output, timeout,
and the distinction between cached image identity and rollback approval.

## No-go and next legitimate evidence

No accessible cache match was found, so the next safe work is **source
and registry archaeology**, with immutable provenance and owner review:
identify original build/run recipes, original source revision, image
manifest/config layer digests and registry/archive recovery candidates.
Do **not** equate a private Docker `export` tar with an OCI image. If
reconstructing from archived source/rootfs, label it a **derived** image
and independently review secrets, entrypoint/user, build reproducibility
and old routes before any isolated dry run.

To unblock issue #50, both old web and API must be launchable from
retained private image artifacts (or independently approved equivalent),
with no public ports/production mounts, demonstrated legacy health/route
and auth behavior, and a tested reversible rollback. Separate database
and MinIO backup restoration, OIDC, independent custody, human SSH
approval and exact-head hosted CI remain required.

**No production containers, models, services, credentials or storage
volumes were modified. Deployment remains HOLD.**
