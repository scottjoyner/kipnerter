# Production PostgreSQL role census — read-only

**Release classification: NO_GO.** This utility measures **only aggregate PostgreSQL role and session counts**, without exposing role names, connection strings, environment entries, credentials, SQL query results from application tables, or raw server error messages.

The source-controlled `scripts/portal_postgres_role_privilege_readonly.py` is a strict, operator-opt-in diagnostic. Its default invocation exits 3 with `DRY_RUN_NO_DOCKER_OR_SQL`. With `--inspect-live` it requires the exact production host `kipnerter-prod-01`, refuses Docker daemon/environment overrides, checks the original production PostgreSQL Docker image ID, and runs exactly two fixed, bounded SELECT-only aggregate queries. Failed probes return only a sanitized HOLD classification. This script must not be run on an unapproved replica or Docker target.

Tests: `python3 -m pytest -q scripts/tests/test_portal_postgres_role_privilege_readonly.py`.

On October 23, an earlier manually performed physical PostgreSQL read-only probe observed 15 roles, one login-enabled superuser, and 3 of 3 sampled client-backend sessions with superuser privileges, including the diagnostic connection. The proposed utility has no way to determine which app or worker owns each session; role counts and a sampled session census are **not** proof of application credential attribution.

No outcome permits release. All results preserve `postgres_writes_fenced=false`, `minio_writes_fenced=false`, `safe_to_cutover=false` and `release_gate=NO_GO`. Elevated MinIO identities, queued effects, external writers, key custody, atomic backup/recovery, and browser OIDC acceptance remain distinct gates. Refer to [Kipnerter P0 #88](https://github.com/scottjoyner/kipnerter/issues/88). No production role changes or credentials are included here.
