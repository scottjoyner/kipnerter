# Production storage image preservation — October 21, 2026

**Scope:** exact **image binaries only** from the existing `kipnerter-prod-01` Docker image cache. No PostgreSQL database rows, MinIO bucket objects, volume mounts, secrets, or application-state backups were transferred, and no production service or registry image was changed. The production access principal was the workflow's intended non-root Tailscale SSH user `kipnerter`, not an alternative bypass account.

## Evidence and private archives

Both original images were read through `docker save` streamed over an authenticated Tailscale SSH session to `x1-370`. Files are **private local artifacts**, mode `0400`, under `/home/scott/git/.kipnerter-prod-image-custody-20261021` (directory `0700`). **Do not add the tar archives to Git, CI artifacts, or public issue comments.**

| Role | Exact running Docker image ID | Local archive SHA-256 | Archive bytes |
| --- | --- | --- | ---: |
| spatial-postgres | `sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` | `9b43dea16fe65102cf2149f67cf8d9f190601fff24ff70a36e0128d69731e30f` | 212,656,128 |
| spatial-minio | `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e` | `ff5c117e1c9bb62adb75c040abdcaa7501f0810c3ec4f18098501ba669516ace` | 62,259,712 |

These image IDs were independently **read back from the running production containers and Docker image metadata** before export. The active Compose file uses mutable tags `postgis/postgis:16-3.4` and `minio/minio:latest` (the exact MinIO registry digest could not be verified from `x1-370`), so archive preservation matters for release recovery. This receipt describes same-administrator evidence, **not independently controlled custody**. Hashes alone do not prove registry authorship, security or restorable data.

## Offline, read-only verifier

The new bounded verifier accepts the exact observed roles (no arbitrary operator-provided digest), verifies every included blob digest and uncompressed diffID, and handles Docker's nested multiarchitecture manifest index, selecting exactly one `linux/amd64` manifest. It rejects missing/replaced blobs, false image IDs, wrong architecture, changed layers, incompatible Docker manifests, and traversal paths. It **does not import or extract archives**.

```bash
cd /home/scott/git/kipnerter-storage-oci-archive-verifier-20261021
python3 -m scripts.portal_stateful_oci_archive_verify \
  --role spatial-postgres < /home/scott/git/.kipnerter-prod-image-custody-20261021/production-postgis-exact-running-20261021.docker.tar
python3 -m scripts.portal_stateful_oci_archive_verify \
  --role spatial-minio < /home/scott/git/.kipnerter-prod-image-custody-20261021/production-minio-exact-running-20261021.docker.tar
python3 -m pytest -q scripts/tests/test_portal_stateful_oci_archive_verify.py
```

The verifier results are `OCI_CONTENT_TREE_VERIFIED_NOT_RESTORED`, **never production release approval**. The private archives must also be rehashed against the listed tar SHA-256 receipts before reuse. Do not assume an archive is independently custodied because it is on a second physical host: the owner/admin credentials remain shared.

## Remaining release hold

- No live PostgreSQL **data backup** or MinIO **object-store backup** was created or transferred as part of this activity.
- No disposable image **launch** or database/object **restore rehearsal** was executed, and the production database and volumes were not modified.
- Independent witness custody, signed high-water checkpoint, backup generation and physical restore evidence remain outstanding.
- Production's `/opt/kipnerter/current` managed-release symlink and release directory are absent; that legacy layout must not be auto-migrated.
- Real Tailnet `tsidp` enrollment/OIDC browser acceptance and production cutover approval remain independent requirements.
- No new DigitalOcean Droplet, cloud firewall, DNS change, public Funnel, model routing, agent execution, or production deployment occurred.
