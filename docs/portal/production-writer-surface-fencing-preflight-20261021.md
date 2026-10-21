# Production writer surfaces — prerequisite to any coordinated recovery checkpoint

**Read-only Fleet Commander observation on `kipnerter-prod-01`, October 21, 2026.**

The storage-recovery research in PRs #69–#75 has demonstrated exact-image
recoverability, old production backup recovery, fresh PostgreSQL restoration,
and fresh MinIO object-content parity across a short observation interval.
**None proves writes were fenced or PostgreSQL and MinIO were checkpointed at
a single instant.** This document identifies the real production Docker
network surfaces that must be reviewed before any operator-approved writer
quiescence or production cutover. It does NOT implement writer fencing.

## Physical evidence

Run the verifier source read-only over the *already approved* Tailscale SSH
principal, never an alternative transport or credential bypass:

```sh
# On x1-370, against the exact reviewed source checkout:
python3 -m scripts.portal_production_writer_surface_readonly
# Exits 3: safe default, no Docker commands.

tailscale ssh kipnerter@100.82.144.33 'python3 - --inspect-live' \
  < scripts/portal_production_writer_surface_readonly.py

# Pure offline security tests; do not contact production:
python3 -m pytest -q scripts/tests/test_portal_production_writer_surface_readonly.py
```

The only Docker operations used are `docker ps --no-trunc -q` and
`docker inspect --type=container` for precisely those currently running
container IDs. The script runs only on hostname `kipnerter-prod-01`; it
rejects ambiguity, missing required services, unknown image IDs, duplicate
container names, stopped containers, unexpected peers and failed reads.
**No environment values, credential contents, SQL queries, storage object
names, volume contents or raw Docker inspection JSON are printed.**

| Observed property | Result |
| --- | --- |
| Required containers | **7/7 running** |
| Unexpected running containers | None |
| Postgres image ID | Exact preserved `sha256:44126d8...` |
| MinIO image ID | Exact preserved `sha256:14cea49...` |
| Postgres attached to internal `kipnerter_spatial_backend` | Yes |
| MinIO attached to internal `kipnerter_spatial_backend` | Yes |
| MinIO also attached to `kipnerter_frontend` | **Yes** |
| `spatial-api` / `spatial-worker` running | **Both** |
| PostgreSQL network-connected peer candidates | Spatial API, spatial worker, MinIO |
| MinIO network-connected peer candidates | Spatial API, spatial worker, Postgres, web, API, Caddy |
| Network/credential/client write fence established | **No** |
| Backend transactions and worker queues drained | **Not verified** |
| Multi-service consistent checkpoint | **Not proven** |

The word **candidate** is intentional: sharing a Docker network demonstrates
connectivity potential, not possession of write credentials or proof that a
service actually writes. Conversely, an empty transaction list or unchanged
object fingerprint is not a durable write fence: an unseen writer can start
between observations. The actual spatial worker, separate API, Caddy/frontend
network, credentials and any external clients must all be addressed.

## Required follow-up before seeking maintenance permission

1. Identify the authoritative owner and every writer of PostgreSQL and
   MinIO, including web/API path, background workers, retry/outbox queues,
   direct S3 credentials, external clients, provisioning jobs and administrative
   access. Prove service-to-resource binding, not just container names.
2. Design a **fail-closed, reversible write-admission barrier** with a
   single operator-authoritative epoch, client revocation, per-resource
   enforcement and explicit refusal of stale/replayed write permits. Verify
   this independently in disposable replicas before any production action.
3. Prove no writes can pass the barrier through any Docker network, S3
   credential, direct Postgres connection, queued worker or emergency bypass.
   Drain in-flight requests, transactions, jobs and durable effects; require
   read-back and negative testing from independent clients.
4. Only with approved maintenance, enforce the fence, capture both storage
   services against a documented recovery checkpoint and observe S3 object
   and PostgreSQL transaction invariants. Generate a signed checkpoint with
   an **independent** key custodian and high-water/revocation guarantees.
5. Restore both databases and S3 objects to an isolated destination, prove
   cross-resource identity and object integrity, conduct rollback and release
   the fence only after a separately authorized decision.

**Do not** equate pausing `spatial-api`, pausing Docker, blocking Caddy,
observing read-only S3 hashes, or taking sequential snapshots with an
atomic writer-fenced multi-service checkpoint. Do not run destructive
network or credential changes merely to satisfy this preflight.

All machine output is deliberately `release_gate=NO_GO`,
`postgres_writes_fenced=false`, `minio_writes_fenced=false`,
`atomic_multi_service_checkpoint_proven=false`,
`independent_administrative_custody=false` and
`safe_to_cutover=false`, regardless of a green inventory. Real Tailnet
`tsidp` enrollment/OIDC browser acceptance and approved production managed
release migration remain separate release blockers.
