# Private off-host rehearsal of an existing production-generated backup

**Physical milestone: October 21, 2026.** The protected production backup
set `ios17-precutover-ad4cffe6e1fe` was already present under the
`kipnerter` account on the existing DigitalOcean production host. It predates
the currently deployed private portal (0cb5937). This workflow **does not**
create a new backup or claim that this older backup contains the latest data.

The exact three pre-existing backup members are deliberately pinned by name,
byte length, and SHA-256 in
`scripts/portal_private_production_backup_offhost_rehearsal.py`. The source
receipt additionally authenticates archive lengths/hashes *within the original
same-operator backup set*. The independent file-level digests were read from
the production host via authorized, read-only Tailscale SSH.

## Operator command (x1-370 only)

```sh
# Deny-only by default, never invokes SSH or Docker:
python3 -m scripts.portal_private_production_backup_offhost_rehearsal

# Explicitly allow remote read-only access to the pinned files and local scratch:
python3 -m scripts.portal_private_production_backup_offhost_rehearsal --execute

# Pure offline negative tests; no real production data:
python3 -m pytest -q scripts/tests/test_portal_private_production_backup_offhost_rehearsal.py
```

The script permits execution only on `x1-370`, after verifying `/dev/shm` is
mounted as Linux `tmpfs` with a sticky world-writable root, and only if the
**exact** two production image IDs are locally imported and still match the
running production container image metadata. SSH is pinned to the already
approved `kipnerter@100.82.144.33` account. Its remote commands are limited to
`docker inspect` and size-capped `head` reads of those three fixed backup
paths. No production Docker writes, database queries or service changes occur.

The archive bytes exist temporarily under a private directory in RAM-backed
`/dev/shm`, created with restrictive `0700` folders and `0600` files. The
existing `portal_state_restore_rehearsal` verifier checks private file
descriptors, exact archive bytes and JSON receipt fields, and runs isolated
scratch PostgreSQL and MinIO containers using the imported **exact original
production image IDs**. It does not mount or read any production Docker volume.
Cleanup deletes the RAM-only archive copies and stops/removes the disposable
containers; the wrapper returns counts and booleans, not rows, object keys,
credentials or backup bytes.

## What actually passed

- Production receipt and private archive checks passed on the source host.
- Both original backup payloads were transferred over Tailscale into RAM-only
  storage, then checked against pinned fixed-content SHA-256 values.
- `pg_restore` restored the existing 52,881-byte production-generated custom
  PostgreSQL dump into a fresh network-disabled scratch database; **50 user
  tables** were observed.
- A network-disabled, isolated MinIO scratch server started successfully using
  the extracted 84,992-byte original raw object-storage archive. This proves
  basic server startup, **not S3 object inventory parity**.
- All temporary remote backup copies on `x1-370` were deleted; the two
  disposable scratch containers were stopped and removed.
- The real production PostgreSQL and MinIO containers/volumes stayed running,
  unchanged. Public chat remained unavailable, and the private portal's
  `0cb5937` build stayed healthy.

## Still blocked

This evidence is **not a real production rollback authorization**. Specifically,
this backup set dates from older source `ad4cffe6`; it is not a verified
current backup or independently custodied snapshot. The MinIO backup was a
raw copy of live backing files, with no point-in-time consistency guarantee
and no comparison of production/live versus restored S3 object listings or
hashes. Operator-controlled archive hashes and a successful local restoration
do not establish independent administrative trust or replay-resistant
high-water custody. Tailnet OIDC/tsidp remains unenrolled, and the managed
production release migration and public traffic cutover have not been approved.

Neither raw backup bytes nor object names/table data should ever be attached
to GitHub issues, PRs, or hosted CI. The wrapper reports
`release_gate=NO_GO` and `safe_to_cutover=false` in all cases.
