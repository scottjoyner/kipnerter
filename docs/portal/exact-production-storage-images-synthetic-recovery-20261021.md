# Exact-image synthetic storage recovery rehearsal — October 21, 2026

**Status: executable synthetic data restore PASS, production-data restore NOT PROVEN.**

The existing production PostgreSQL and MinIO Docker image caches were copied
read-only through the authorized, non-root `kipnerter` Tailscale SSH account from
`kipnerter-prod-01` to owner-private files on `x1-370`. They were verified
as complete OCI archive content trees (including compressed blob digests and
uncompressed layer diffIDs), then imported locally with `docker load
--platform linux/amd64`. **No image was pulled from a registry as part of this
rehearsal.** Docker verified that the imported image IDs exactly match the
currently running production images:

| Role | Required image ID | Archive SHA-256 |
| --- | --- | --- |
| PostgreSQL/PostGIS | `sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` | `9b43dea16fe65102cf2149f67cf8d9f190601fff24ff70a36e0128d69731e30f` |
| MinIO | `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e` | `ff5c117e1c9bb62adb75c040abdcaa7501f0810c3ec4f18098501ba669516ace` |

**Executable reproduction (on `x1-370` only)** after verifying and privately
importing both original archives:

```sh
# Default fails closed without invoking Docker.
python3 -m scripts.portal_exact_storage_image_synthetic_rehearsal

# Explicit operator request: temporary, network-disabled synthetic tests.
python3 -m scripts.portal_exact_storage_image_synthetic_rehearsal --execute

# Non-Docker tests that verify isolation, identity and cleanup controls.
python3 -m pytest -q scripts/tests/test_portal_exact_storage_image_synthetic_rehearsal.py
```

The `--execute` action refuses all hosts except `x1-370` and refuses image
IDs differing from the two exact production image IDs. It starts temporary
`--network none`, `--read-only`, `--cap-drop ALL` non-root Docker
containers, with cgroup resource limits, no host ports, no bind mounts, and
only disposable tmpfs storage. Every container is inspected after creation
and removed by its exact Docker ID even if a later test fails.

For **PostgreSQL**, the runner creates a 1-row synthetic table and verifies
`pg_dump -Fc` followed by `pg_restore` into a second scratch database.
For **MinIO**, it runs two entirely network-disabled instances from the
preserved exact image, uses an ephemeral local `mc` CLI alias, writes
synthetic bytes into the source instance, streams the object back into the
independent scratch destination instance, and verifies the restored SHA-256.
All credentials and object contents are generated test values. No private
production records or MinIO bucket objects are accessed.

The physical result on October 21 was `SYNTHETIC_EXACT_IMAGES_PASS_NOT_PRODUCTION_RESTORE`,
with a synthetic PostgreSQL custom-format dump of 1,716 bytes and MinIO
restored object length 3,684 bytes and SHA-256
`6ca1a78c1d9e571221bc6833f59fd0db576b615148c4f77d35b97b8596c6017e`.
All test containers were removed, and the healthy private portal remained
on its existing exact-release SHA. No public production deployment occurred.

**Explicit holds:** image-launch proof is not a production PostgreSQL restore,
MinIO backup/restore, consistent point-in-time snapshot, signed high-water
checkpoint, independent administrative custody, real Tailscale OIDC login,
managed release migration, or authorized cutover. Actual production database
and object-store backup payloads were **not** captured by this milestone.
No production services/volumes/data, DigitalOcean resources, Tailscale ACLs,
public DNS, or Funnel were modified. Raw OCI archives remain private and are
**never** committed to Git or uploaded to hosted CI.
