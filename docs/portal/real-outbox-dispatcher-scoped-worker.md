# Real OutboxDispatcher: separate worker database authority

**Physical isolated result — October 24, 2026:** `REAL_SPATIAL_OUTBOX_DISPATCHER_SCOPED_PASS`; source production release **NO_GO**.

After merged [PR #93](https://github.com/scottjoyner/kipnerter/pull/93) verified all four original spatial Alembic upgrades with a separate synthetic migrator, this follow-up tests the **actual deployed** `kipnerter_api.outbox.OutboxDispatcher` against the migrated database in a disposable PostGIS container on an internal-only Docker network.

A separate restricted synthetic worker receives only **SELECT and UPDATE** on `outbox_events`, not INSERT, role administration, schema ownership, or access to unrelated API tables. The synthetic migrator seeds event data, without implying it is the desired production API producer. The real dispatcher then claims two events, successfully handles/acknowledges one, dead-letters a missing-handler event, releases both locks, and does not reclaim finished events. A separate event exercises the real transient-handler-error path, honoring the retry delay before the second attempt publishes it and releases its lease. Worker attempts to INSERT outbox rows, read the `devices` table, ALTER outbox schema, SET ROLE migrator or edit `alembic_version` all fail.

This tests permission sufficiency for **claiming, publishing, retrying and dead-lettering**, not that every actual background handler or upstream producer works with these grants. The retry clock is advanced only by the synthetic migrator inside the disposable database; no source production messages are read, claimed or modified. The deliberate synthetic handler failure appears as a stack trace in the disposable test log but does not leak secrets or represent a production incident.

The source-controlled `scripts/portal_real_spatial_outbox_leases_scoped.sh` defaults to `DRY_RUN_NO_DOCKER_ACCESS`. Only an explicit `--execute` on x1-370's default local Docker context runs; exact original API and PostGIS Docker SHA256 IDs are required. Only internal Docker networking, bounded tmpfs, read-only container roots and ephemeral generated passwords are used. All scratch containers and test network are deleted on exit. No ports, host mounts, production credentials, object-storage data or remote database connections.

Run:

```bash
bash scripts/portal_real_spatial_outbox_leases_scoped.sh
bash scripts/portal_real_spatial_outbox_leases_scoped.sh --execute
python3 -m pytest -q scripts/tests/test_portal_real_spatial_outbox_leases_scoped.py
```

The production spatial API and worker currently share privileged PostgreSQL and MinIO-root credentials as established in merged [PR #91](https://github.com/scottjoyner/kipnerter/pull/91), and require a real permission/credential rollout with rollback. This test does not cover the other application/worker tables and PostGIS operations, independent migrator custody, actual external/S3 identities, full background job handlers, server-enforced multi-store fencing, write-fenced atomic capture, private OIDC acceptance or original legacy OCI restore.

**Release invariant:** `production_modified=false`, `source_writes_fenced=false`, `safe_to_cutover=false`, `release_gate=NO_GO`. P0 tracked by [issue #88](https://github.com/scottjoyner/kipnerter/issues/88).
