# Actual deployed spatial Alembic migrations with separated service identities

**Physical isolated result — October 24, 2026:** `REAL_ALEMBIC_MIGRATED_SCOPED_ORM_PASS`. **Production release remains NO_GO.**

## Reproducible test

The operator-only `scripts/portal_real_spatial_alembic_migrator_rehearsal.sh` uses the exact production spatial Python image `sha256:1624c272977968a700ca6f4b37107c46ec5bd35c7122cd6566fa7b7c8674a8e8` and exact PostgreSQL/PostGIS image `sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5`, **without reading or changing production data**.

Only on x1-370 with an explicit `--execute`, local default Docker context, and pinned local images will the test create a disposable **Docker internal-only network**, bounded RAM-backed database volume, read-only container roots, and per-run randomized *synthetic* credentials. The default invocation does not access Docker and returns `DRY_RUN_NO_DOCKER_ACCESS`.

The separate, synthetic `spatial_migrator` runs the original deployed application's four Alembic upgrades to version **`20260817_0004`**, verified directly in the disposable database. Then two distinct synthetic PostgreSQL login roles are created with NOINHERIT, NOSUPERUSER, NOCREATEROLE, NOCREATEDB, NOREPLICATION and NOBYPASSRLS. Their grants are limited to API `devices` and worker `outbox_events` for the deliberately bounded smoke test.

Both roles successfully run real SQLAlchemy ORM INSERT and SELECT using installed `DeviceModel` and `OutboxEventModel`. They fail attempts to access the other service's table, ALTER/DROP application tables, CREATE ROLE, impersonate the migrator, and tamper with `alembic_version`. The original separate migration account is not used by either running test application principal. All scratch containers and networks are deleted after the test.

Run offline contracts: `python3 -m pytest -q scripts/tests/test_portal_real_spatial_alembic_migrator_rehearsal.py`.

## Limits and dependencies

This is a **real migration plus scoped-role smoke test**—not a fully authorized production database migration plan. Migration ownership remains a privileged operation that needs real independent control; rotating the production superuser credentials or starting Alembic from a live API with those credentials may disrupt service. The full 12-table permission matrix, application endpoint workflows, outbox leasing, geometries, S3 access policies, external/administrator writer identities, connection pool invalidation, migration rollback, release fencing, and current physical build/IdP gates are not covered.

The installed spatial source was custody-verified independently: 43 allowlisted files in x1 owner-private storage and 21/21 Python code files matched to the production Docker image by SHA256. The deployed tree has no Git commit provenance; pin to exact image identity rather than assigning it an unrelated Git commit.

No production PostgreSQL roles, SQL objects, MinIO keys, Docker Compose services, DNS, authentication policies, access controls, or ingress changed.

**Release invariants:** `production_modified=false`, `source_writes_fenced=false`, `safe_to_cutover=false`, `release_gate=NO_GO`. Track [P0 #88](https://github.com/scottjoyner/kipnerter/issues/88) and [release issue #19](https://github.com/scottjoyner/kipnerter/issues/19).
