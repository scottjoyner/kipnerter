# PostgreSQL API/worker least-privilege rehearsal (synthetic)

**Test classification: SYNTHETIC_SCOPED_API_WORKER_AUTHORIZATION_PASS. Release gate: NO_GO.**

This is a disposable-only acceptance slice of [P0 #88](https://github.com/scottjoyner/kipnerter/issues/88). On x1-370 the operator explicitly runs `bash scripts/portal_synthetic_postgres_service_roles.sh --execute` against an exact-pinned, already cached copy of the original production PostgreSQL image, with **network none**, a read-only root filesystem, bounded RAM-backed storage, and no host data mounts. All schemas, rows, accounts, and per-run generated credentials are fake. The default without `--execute` returns `DRY_RUN_NO_DOCKER_ACCESS` and performs no Docker operations.

The synthetic API and worker receive **distinct LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS** accounts. Each can INSERT and SELECT its own table. Each is denied reads and writes to the other service's schema, unauthorized DDL, CREATE/ALTER ROLE and SET ROLE to the privileged database administrator. An aggregate role-catalog check confirms both scoped roles have no privileged flags or role memberships. All temporary containers are removed automatically.

The physical test is **not an actual production migration**. It does not establish the privileges required by real API ORM queries, PostGIS, migrations, multi-schema joins, worker jobs, queue processing or app startup. A proper transition must inventory real schema/function/sequence usage, map connection principals and MinIO identities, validate workloads on a restored isolated replica, stage rollback credentials without leaking them, and demonstrate that every privileged or external writer is truly barred by a resource-enforced fence. Existing production superuser login remains active and unchanged.

Run synthetic test controls using `python3 -m pytest -q scripts/tests/test_portal_synthetic_postgres_service_roles.py`. This test never supplies authority for a source write fence or public release; `source_writes_fenced=false`, `safe_to_cutover=false`, `release_gate=NO_GO` remain immutable results.
