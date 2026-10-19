# State recovery topology qualification (read-only)

This is a configuration gate, NOT a backup or a rollback procedure. Deployment
remains on HOLD until a separately tagged staging host, immutable image
identities, and an actual independently witnessed database/object restore.

## Actual Compose observations — October 19, 2026

| Environment | Project | PostgreSQL named volume | MinIO named volume |
| --- | --- | --- | --- |
| Production | kipnerter | kipnerter_spatial_postgres_data | kipnerter_spatial_minio_data |
| Staging | kipnerter-staging | kipnerter-staging_spatial_postgres_data | kipnerter-staging_spatial_minio_data |

Staging's API and web origins are separate from production. PostgreSQL is on
an internal Compose network. The selected database and object-store volumes
each have a single expected owning service and no published host ports.

The new scripts/portal_state_recovery_preflight.py reads a Docker Compose
config JSON document on stdin and does not contact Docker, databases, object
storage, or remote fleet nodes. It emits only project name, storage names,
targets, a topology fingerprint, blockers and explicit false restore flags.
It returns code 2 if topology is qualified but immutable image evidence is
missing, and rejects invalid config without emitting a receipt.

Actual staging and production results both returned code 2 / RELEASE HOLD:
- Postgres/PostGIS image postgis/postgis:16-3.4 is mutable (no pinned digest).
- MinIO image minio/minio:latest is mutable (no pinned digest).
- Neither a PostgreSQL restore nor a MinIO object recovery was executed.
- No production source-and-volume restore equivalence was proven.

Do not save raw resolved Compose JSON in logs or release artifacts; real
config can contain secrets. Pipe it directly into the read-only analyzer.

## Smallest safe future restore acceptance procedure

1. Independently provision a staging-tagged host with bounded free capacity.
   Production's host is not an acceptable synthetic rehearsal substitute.
2. Inspect architecture-specific PostGIS and MinIO image digests. Pin a known
   compatible image version and record its immutable identity.
3. Create isolated synthetic Postgres and MinIO fixtures in brand-new volumes;
   record row counts, schema version, object inventory, lengths, and SHA-256.
4. Quiesce fixture writers and create a consistent database dump and MinIO
   snapshot. Capture checksums and provenance in a separate private custody
   directory.
5. Deliberately mutate the synthetic fixtures, then restore into DIFFERENT
   new volumes, not the original staging or production volumes.
6. Compare schema, row counts, object inventory and per-object digests. Prove
   that truncated or tampered backups fail before changing active services.
7. Rehearse source rollback against restored fixture volumes and verify
   independent Tailscale OIDC browser login and exact source build witnesses.

This procedure remains a runbook. A valid topology receipt or synthetic
restore alone does NOT authorize production recovery, require privileged
access, or prove owner-bound model execution. No containers, volumes,
credentials or live services were modified in this analysis.
