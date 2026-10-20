# Destroyer: pinned MinIO S3 synthetic copy/parity rehearsal

**Research-only.** A portable, inspectable physical fixture that works around
the license-blocked AIStor candidate without claiming production recovery.

## Physical observation — 2026-10-20

Fleet Commander read-only inventory found these **already cached** local
images on `destroyer`:

| Role | Version | Pin (local image ID) |
| --- | --- | --- |
| MinIO server | `RELEASE.2025-07-23T15-54-02Z` | `sha256:a98a9d647e700e45c1d3d2e44709f23952a39c199731d84e623eb558fd5501f4` |
| MinIO `mc` | `RELEASE.2025-07-21T05-28-08Z` | `sha256:e1497f813d2de5084b2bd38df37f8e68a999be6af10b4c495ae7c3eaf081a9ce` |

The host reported about 3 GiB memory available and ~74 GiB free scratch disk
during preflight. The test uses about 1 GiB of bounded container memory,
and object payloads below 1.3 KiB. It performs no disk image pulls/builds.

**Physical experiment:** a source server and restoration-target server ran
with separate `/data` and `/tmp` Docker tmpfs mounts; the source used
`--network none`. Target server and `mc` joined **only the source's
isolated network namespace**, listening to localhost ports 9000 and 9001;
no outside network and no host-published ports. Each server had independently
generated, **synthetic** root credentials; no production secret or user data
was passed. The original production MinIO installation was not contacted.

An object of 1,070 bytes was written using `mc pipe`, read back using
`mc cat` and compared to the caller-known SHA-256. Then `mc cp` copied the
same object into the second independent server; its `mc cat` bytes and
SHA-256 matched the source. A synthetic altered payload produced a
different SHA-256 (negative integrity control). Both containers were
force-removed after testing; the following read-only inventory found no
remaining synthetic containers. An earlier first attempt had a transient
`mc pipe` failure despite successful bucket listing; the remote helper
now bounds upload retries to three before reporting HOLD.

## Reproduction and safety envelope

From the **authorized x1-370 worktree** only:

```sh
python3 scripts/portal_minio_offhost_s3_fixture.py
```

The entrypoint only uses the hard-coded, host-key-checked SSH alias
`destroyer` (BatchMode, no TTY, no forwarding), verifies a 256-bit nonce
in the bounded reply, and runs the version-controlled
`portal_minio_disposable_remote.py` from remote Python memory.
It does not upload or install the source file on the remote host.

The remote program checks both image IDs against the reviewed local image
pins **before launching**. It has no Docker bind mounts, persistent volumes,
published ports or production paths. Docker scratch memory, time, CPU,
process counts, and individual calls are capped. All temporary containers
are removed in a `finally` block. Synthetic passwords are never included
in JSON responses. The test's stdout is safe metadata only.

Result `SYNTHETIC_ONLY_PASS` is **not** a release authorization. Both
the remote and caller fail closed if anything asserts a production image
identity, external custody, production backup restoration, live data access
or cutover approval. Even the successful result must report:
`minio_prod_image_identity_verified=false`,
`real_backup_restored=false`,
`independent_custody_verified=false` and
`production_recovery_approved=false`.

## Real recovery work still missing

* Identify original production MinIO image (or independently approve
  compatible version) and pin immutable digest plus configuration.
* Verify private source backup inventory, provenance, timestamp consistency,
  encryption/key custody and volume/object safety without exposing raw data.
* Restore PostgreSQL and MinIO **real backups** into dedicated isolated staging,
  compare expected table/object inventories and cryptographic content evidence
  with independently approved baseline records.
* Independently administer the checkpoint/cursor publication role and test
  full-state rollback, revoked identities and replay after restart.
* Retain independently runnable web and API rollback artifacts (issue #50),
  exact-head hosted CI, human acceptance and production authorization.

This test does not prove a raw MinIO storage-directory backup can be mounted
by the 2025 image, that live application keys match, or that any production
backup exists or is complete. It never serves public endpoints.
