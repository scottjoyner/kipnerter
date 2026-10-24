# Real spatial API ORM + scoped PostgreSQL roles: isolated acceptance slice

**Physical result, 2026-10-23:** `REAL_SPATIAL_ORM_SCOPED_ROLE_SMOKE_PASS`. This is **not** production writer fencing or release authorization.

## Grounded source and images

The actual running spatial API Docker image `sha256:1624c272977968a700ca6f4b37107c46ec5bd35c7122cd6566fa7b7c8674a8e8` was copied **read-only** over authenticated SSH from `kipnerter-prod-01` onto x1-370. Its installed Python package had **21 of 21** code-file SHA-256 matches against the private owner-only production source custody directory `~/.local/state/kipnerter-spatial-source-custody/20261023-production` (custody manifest SHA-256 `9f15eda47f1ca265a95c4c5cb8627641c4dd142577ca6867a61282ef7195e10a`). The source lacks a verified Git commit; do not substitute a repository HEAD as evidence of the deployed image.

The PostgreSQL/PostGIS image is pinned to `sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5`.

## Operator-only isolated test

The script `scripts/portal_real_spatial_orm_scoped_roles.sh` defaults to `DRY_RUN_NO_DOCKER_ACCESS`; it only runs with **explicit** `--execute` on x1-370's default local Docker context when both exact images exist. It creates a disposable **Docker internal-only network**, a read-only-root PostGIS container with bounded tmpfs and no published ports, synthetic random-per-run passwords, and a disposable application container with a read-only root filesystem. The complete network and containers are removed on exit. **No production databases, buckets, credentials, volumes, public ingress, Tailnet policy, or images are changed.**

The *actual deployed* SQLAlchemy ORM models created **12 tables and 13 foreign-key constraints** in the isolated PostgreSQL instance. Distinct synthetic non-superuser API and worker roles received only the specific required test grants: API SELECT/INSERT on `devices`, worker SELECT/INSERT on `outbox_events`. ORM INSERT and SELECT succeeded for both actual model classes (`DeviceModel` and `OutboxEventModel`). Cross-service SELECT, unauthorized schema DDL and role creation were rejected. This verifies a narrow real-model role separation slice, **not every API/worker operation**.

Run:

```bash
bash scripts/portal_real_spatial_orm_scoped_roles.sh                 # no Docker access
bash scripts/portal_real_spatial_orm_scoped_roles.sh --execute       # isolated sandbox only
python3 -m pytest -q scripts/tests/test_portal_real_spatial_orm_scoped_roles.py
```

## Still-open production release gates

The live API and worker both currently share a PostgreSQL **superuser** login and the actual running MinIO **root access identifier and secret pair** (physically verified with read-only, no-secret [PR #91](https://github.com/scottjoyner/kipnerter/pull/91)). Their real endpoints, PostGIS spatial reads/writes, background processing, migrations, complete 12-table privilege needs, S3 bucket policies, alternate keys and worker queues must be exercised under separate scoped identities against a disposable restored snapshot before any production credential rotation. The source write fence, atomic cross-store checkpoint, independent recovery custody and private browser OIDC gates are also outstanding.

**Permanent assertion:** `production_modified=false`, `writer_fence_proven=false`, `safe_to_cutover=false`, `release_gate=NO_GO`.

Tracking: [P0 storage identity issue #88](https://github.com/scottjoyner/kipnerter/issues/88), [release issue #19](https://github.com/scottjoyner/kipnerter/issues/19).
