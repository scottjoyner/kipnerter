# Historical MinIO backup — live S3 object parity witness

**Observed October 21, 2026.** Read-only owner-private comparison of the
previously captured production MinIO raw-data backup
`ios17-precutover-ad4cffe6e1fe` with the live MinIO service.
**This is not a point-in-time-consistent snapshot, a fresh backup, or an
approval to deploy production.** No production objects were modified.

## Bounded operator reproduction (x1-370 only)

```sh
# Default performs no SSH or Docker operations:
python3 -m scripts.portal_private_minio_offhost_s3_parity

# Explicitly compare the original backup with live MinIO without exporting
# production object payloads. Existing trusted Tailscale SSH and private
# original storage-image imports are prerequisites:
python3 -m scripts.portal_private_minio_offhost_s3_parity --execute

# Pure offline failure-injection tests:
python3 -m pytest -q scripts/tests/test_portal_private_minio_offhost_s3_parity.py
```

The verifier is scoped to the **exact original production MinIO image ID**
`sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`,
fixed backup archive/receipt names, byte counts, SHA-256 values, and the
non-root production SSH principal `kipnerter@100.82.144.33`.

Production executes only the existing `portal_minio_s3_parity` **read-only**
listing and bounded content hashing functions with Docker exec, using the
running MinIO server's credentials *only within its container*. The
production host sends the off-host verifier **only sanitized object counts and
SHA-256 fingerprints**. No bucket keys, object payloads, credential strings,
object URLs or SQL rows appear in witness output. Content checks cap objects
to 32, each at 32 MiB, and aggregate content to 64 MiB; oversized source
objects, responses and malformed/duplicate JSON fail closed.

On `x1-370`, only the existing private MinIO archive and receipt are read
through bounded Tailscale SSH and copied into mode-0600 temporary files in a
mode-0700 folder on verified RAM-backed `/dev/shm`. The existing hardened
MinIO snapshot extractor validates archive bounds and restores the raw files
under a temporary, network-disabled MinIO container with no host ports or
production volume mounts. The restored MinIO S3 inventory and each object's
**actual byte-content hash** are compared against the sanitized live witness.
Production is checked again after the off-host restore; changed metadata or
content fingerprints fail closed. The temporary data and container are
removed after the test.

## Physical observation

| Property | Live S3 | Off-host restored S3 |
| --- | --- | --- |
| Expected bucket present | Yes | Yes |
| Objects | 2 | 2 |
| Bucket/object metadata SHA-256 | `fae31b07ca0c4887606af3adda465a4b54440d442f9635575247ac605ac74603` | Same |
| Content inventory SHA-256 | `4c21c9e46dfb029607465df9af404903b18c7bdab76fe30ac1295ca6c627a958` | Same |
| Source writes fenced? | No | Not applicable |

Both the exploratory physical comparison and the repeatable implementation
passed. Cleanup checked RAM backup directories and scratch containers absent.

## Interpretation / remaining HOLD

The old backup's **two observed objects match live metadata and contents**
at the times tested. This is stronger than raw MinIO server startup and is
not a fabricated synthetic-object claim. However, matching fingerprints do
not establish that backup writers were stopped, that PostgreSQL and MinIO
were captured at the same point in time, that no concurrent writes occurred
between checks, or that the backup remains current for a future cutover. The
backup belongs to older staging source `ad4cffe6e1fe`, whereas the private
portal serves `0cb5937` and remains unauthenticated until tsidp enrollment.

No independent administrator custody, replay-resistant signed high-water,
current atomic backup, real browser OIDC acceptance, or approved production
release migration has been proven. The program **always** reports
`source_writes_fenced=false`, `point_in_time_verified=false`,
`safe_to_cutover=false` and `release_gate=NO_GO`.

Do not upload raw S3 objects, credentials, plaintext archives, or user records
to GitHub, CI, or chat. No new DigitalOcean resources, Tailscale ACL grants,
public DNS, or production data writes are part of this workflow.

## Original-image cache eviction observed during verification

During the final test, the original storage image IDs had been evicted from
`x1-370`'s local Docker cache, causing the runner to **fail closed** before
SSH/object access. Production's read-only Docker identity still matched.
The original private MinIO OCI archive remained intact at the pinned SHA-256
`ff5c117e1c9bb62adb75c040abdcaa7501f0810c3ec4f18098501ba669516ace`.
After re-verifying its entire OCI blob/diffID tree, the operator re-imported
only the exact `linux/amd64` MinIO image using `docker load`, independently
confirmed its immutable Docker image ID, and reran the parity check to PASS.
No registry image was silently substituted and **no production host image was
changed**. This is a reproducibility precondition, not reason to weaken the
image-identity gate or automatically pull `minio/minio:latest`.
