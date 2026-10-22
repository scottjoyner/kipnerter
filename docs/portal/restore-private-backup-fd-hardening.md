# Private backup receipt and archive descriptor hardening

## Scope

The real, owner-private `ios17-precutover-<source>` backup rehearsal already
stages two production-generated artifacts: `postgresql.custom` and
`minio-raw-live.tar`, accompanied by `snapshot-receipt.json`.
The snapshot script explicitly says the raw live MinIO directory may not be
point-in-time consistent. Neither a matching SHA-256 nor an S3 server health
check proves point-in-time consistency or content-level recovery.

The previous restore rehearsal checked a pathname and symlink status, hashed
an archive, then opened it **again** for use. Under pathname replacement or
hardlink attacks the inspected bytes need not be the bytes consumed.

## Hardened contract — October 20, 2026

`scripts/portal_state_restore_rehearsal.py` now:
- Opens an owner-private directory through `O_DIRECTORY|O_NOFOLLOW`.
- Uses `os.open(..., dir_fd=...)` with `O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`
  and opens each accepted backup as a read-only file descriptor.
- Rejects files that aren't regular, owner-only (0600 or stricter),
  single-link, same-user records. Also rejects owner-unsafe directories,
  symlinks, FIFOs, arbitrary filenames, oversized receipts, duplicate JSON
  keys, unsupported receipt claims, malformed archive sizes, and hashes.
- Checks both SHA-256 and expected length against a single open file,
  bounding reads to 3 GiB, and detects changes in stat-reported size,
  mtime and ctime while hashing.
- Rewinds **that exact opened archive file descriptor** before handing the
  custom PostgreSQL dump to `pg_restore` or parsing/extracting raw
  MinIO tar contents into isolated scratch staging.
- Requires exact known source SHA, parsed PostgreSQL TOC evidence,
  explicit `safe_to_cutover=false`, and false unearned claims for
  restoration, point-in-time consistency, external custody, or prod changes.

Run dry, synthetic-only tests with:

```sh
python3 -m unittest scripts.tests.test_portal_state_restore_rehearsal \
  scripts.tests.test_portal_private_backup_fd -v
```

These changes **do not** open live database/container state in normal test
execution, retrieve backup bytes from production, access API auth, change
production objects or approve a release. No network calls were introduced.

## Evidentiary ceiling and remaining work

A pinned descriptor prevents the specific pathname-redirect race but **is
not tamper-proof**: the same privileged account, the OS/storage operator, or
independent access to an already-open file can still change data. SHA-256
against an attacker-replaceable receipt isn't an independently retained
signature or append-only high-water witness.

A full restoration requires a source-authoritative and independently retained
manifest; real Postgres restore + table/row integrity evidence; real MinIO
backup recovery and S3 object listing/hash parity with the source,
point-in-time backup consistency, independently controlled keys and
nonrewritable checkpoint custody; plus executable old web/API OCI rollback,
OIDC/release approvals and exact-head CI.

The original `minio_raw_copy_to_disposable_server` claim only covers
scratch mounting/server readiness. It does **not** verify actual objects, and
its enclosing report keeps `minio_object_inventory_compared_to_live=false`,
`minio_point_in_time_consistency_verified=false` and
`safe_to_cutover=false`. No proof status is promoted by this change.
