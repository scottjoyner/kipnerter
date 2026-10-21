# Fresh PostgreSQL + MinIO read-only observation-window rehearsal

**Physical witness:** October 21, 2026, approximately `13:55:09Z` to
`13:55:18Z`, from the permitted `x1-370` Fleet Commander host.

This is a **fresh paired observation with two independent reads**, not a
write-fenced, coordinated database/object-store snapshot. In particular,
PostgreSQL's consistent transaction snapshot and MinIO's raw backing-file
copy were **not** taken at the same atomic instant. Live production writers
were not disabled, locked, or reconfigured.

## What was observed and restored

| Measure | Actual result |
| --- | --- |
| Production PostgreSQL `pg_dump -Fc` | 52,881 bytes, SHA-256 `5a597c377bf7ede388cfd99c5c269a94d6504dcd9814510677d4136655495759` |
| Restored PostgreSQL user tables | 50 |
| Fresh MinIO `docker cp ...:/data -` raw backing-file tar | 59,392 bytes, SHA-256 `9b94c3e5b49994f93780efe2d1b3831f416b11be24c32286f240a5fd7e30fe3b` |
| MinIO tar entries | 53 |
| Restored MinIO S3 objects | 2 |
| Restored S3 object-byte fingerprint | `4c21c9e46dfb029607465df9af404903b18c7bdab76fe30ac1295ca6c627a958` |
| Live S3 metadata fingerprint | `fae31b07ca0c4887606af3adda465a4b54440d442f9635575247ac605ac74603` |
| Live S3 before/after metadata and bytes | Matched |
| Tmpfs backups retained offhost | None — independently verified deleted |
| Scratch containers left running | None — independently verified removed |
| Production files/services/volumes modified | No change requested or observed |

No sensitive PostgreSQL data, S3 object keys, object payloads, credentials,
or raw archive bytes were logged or attached to GitHub.

## Reproduction with strict guardrails

```sh
# Default is NO_GO and runs no remote or Docker actions:
python3 -m scripts.portal_current_pg_minio_readonly_window

# Explicit opt-in on x1-370 only; writes no production data:
python3 -m scripts.portal_current_pg_minio_readonly_window --execute

# Offline negative controls without live SSH, source data or Docker:
python3 -m pytest -q scripts/tests/test_portal_current_pg_minio_readonly_window.py
```

The runner requires original, exact PostgreSQL and MinIO image IDs already
imported on `x1-370`, confirmed against live production read-only
`docker inspect` using only the authorized non-root
`kipnerter@100.82.144.33` Tailscale SSH principal. An absent/mismatched
original image **fails closed**: never pull a mutable registry tag.

Source operations: bounded `pg_dump -Fc` and bounded, read-only
`docker cp kipnerter-spatial-minio-1:/data -`. Both are transferred
only over authenticated Tailscale SSH to owner-private mode-0600 files in
mode-0700 RAM-backed `/dev/shm` scratch. PostgreSQL archive is capped
at 8 MiB, MinIO raw archive at 16 MiB, and both SSH transfers have timeouts.
MinIO tar members are checked before the strict extractor applies its path,
link/type, member-count and expanded-size limits.

The local scratch PostgreSQL container runs on the exact original archived
production image with no network or production volume mounts and restores the
fresh dump. The separate scratch MinIO server also has no external network
or production mounts. Existing bounded S3 inventory/content tooling checks
at most 32 objects, at most 32 MiB per object and 64 MiB aggregate. Raw
production MinIO object bytes are hashed **on production** and only sanitized
metadata/count/fingerprint values leave that host. Source MinIO inventories
are measured before and after the offhost restore; changes fail closed.

## Explicitly unresolved production-release gates

A passing paired read means both datasets were readable and restorable
independently **during that window**; it cannot prove they were captured at
the same instant. A writer could modify either backing store between the
reads and could restore it to the same values. Nothing enforces a global
write fence, independently controlled backup custody, signed checkpoint
high-water, replay/revocation authority, approved identity-provider client,
or real browser OIDC acceptance. This is **not a retained recovery backup**:
RAM-only source copies are intentionally deleted after verification.

Machine output must continue to say
`cross_service_point_in_time_consistent=false`,
`minio_source_writes_fenced=false`,
`postgres_source_writes_fenced=false`,
`independent_administrative_custody=false`,
`real_oidc_browser_login_verified=false`,
`safe_to_cutover=false` and `release_gate=NO_GO`.
Do not stop production writers, change ACLs, promote public routes, or
migrate the managed release on the basis of this check.
