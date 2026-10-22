# Fresh production PostgreSQL dump: RAM-only off-host restore witness

**Date: October 21, 2026.** This check advances beyond restoring the older
`ad4cffe6` pre-cutover backup. It reads a **fresh PostgreSQL custom-format
logical dump directly from the currently running production PostgreSQL
container** and restores that dump into an isolated off-host scratch database.
**It does not collect, modify, back up, or lock live MinIO objects.**

## What ran physically

- The approved production Tailscale principal `kipnerter@100.82.144.33`
  issued only `docker exec -u postgres ... pg_dump -Fc` against the already
  running `kipnerter-spatial-postgres-1` container. This is a read-only logical
  backup command, not `docker cp`, filesystem snapshot, or DB change.
- The exact original production PostgreSQL image ID
  `sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5`
  was restored on `x1-370` from the operator-private immutable Docker archive
  after verifying its archive SHA-256 plus OCI blob and layer diffID hashes.
  No mutable registry image was substituted.
- The **fresh** `pg_dump -Fc` bytes moved only over authenticated Tailscale
  SSH into a mode-0600 file in a private mode-0700 directory backed by
  Linux `/dev/shm` tmpfs. A strict 8 MiB output budget, process timeout,
  custom-format magic check and full SHA-256 guard were enforced.
- The existing TOCTOU-resistant private-file-descriptor verifier restored the
  dump into a disposable `--network none` scratch PostgreSQL container (no
  host ports or production volume mounts). It found **50 user tables**.
  The temporary database and RAM-backed dump were then deleted.
- On the final repeatable run, the dump was **52,881 bytes** and its SHA-256
  was `daa65c3769add10330e5dda0234e7baa7eb39bbada4473da3202a7106343111a`.
  The recorded capture window was `2026-10-21T11:58:15Z` to
  `2026-10-21T11:58:17Z` (UTC). The dump was restored successfully.
- Post-run checks confirmed no leftover scratch containers, tmpfs data, or
  production service changes. The production API remained healthy (200) and
  the private Tailnet chat continued serving `0cb5937`.

## Repeatable operator command

```sh
# Safe default: prints NO_GO; does not invoke Docker or SSH.
python3 -m scripts.portal_current_postgres_tmpfs_restore

# Explicit read-only pg_dump + private ephemeral off-host restore on x1-370.
python3 -m scripts.portal_current_postgres_tmpfs_restore --execute

# Offline negative checks (no production access):
python3 -m pytest -q scripts/tests/test_portal_current_postgres_tmpfs_restore.py
```

Execution is host-restricted to `x1-370` and verifies the exact local/imported
Docker image against the still-running production PostgreSQL image ID before
and after the dump. It never writes the raw dump to the repo, GitHub, cloud
storage, or a persistent disk. It refuses excess/invalid/unbounded data,
unauthorized hosts, changed images, truncated streams or missing tmpfs, and
removes scratch data on failure as well as success. Only bounded counts,
timestamps, hashes and boolean security claims appear in output.

## Release implications and open gates

`pg_dump` provides a transaction-consistent logical PostgreSQL snapshot as
of its own database snapshot, but the backed-up data can change immediately
afterward. Nothing in this run fenced production writers, captured MinIO at
the *same instant*, or established independent custodial ownership.

**Production cutover remains `NO_GO`:** no atomic PostgreSQL+MinIO point-in-time
checkpoint, current write-fenced MinIO snapshot, independent signed high-water
custodian, enrolled Tailscale identity-provider with real OIDC browser login,
or authorized managed-release migration. No production containers/volumes,
Tailscale ACLs, public DNS/Funnel or DigitalOcean resources were modified.
