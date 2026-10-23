# Synthetic PostgreSQL and MinIO write-denial rehearsal — October 23, 2026

**Physical result: SYNTHETIC_STORAGE_ROLE_WRITE_DENIAL_PASS_NOT_FENCED. Public production release remains NO_GO.**

Source-controlled `scripts/portal_synthetic_storage_writer_fence.sh` uses the exact locally cached production PostgreSQL and MinIO image IDs, but no production volumes, network, credentials or account information. It starts disposable network-none containers with bounded tmpfs working data and synthetic-only users, and removes them on exit.

Default invocation `bash scripts/portal_synthetic_storage_writer_fence.sh` returns `DRY_RUN_NO_DOCKER_ACCESS` and exit 3. Only `bash scripts/portal_synthetic_storage_writer_fence.sh --execute` runs the local synthetic exercise, requiring host x1-370, default local Docker context and exact image identities. Offline tests: `python3 -m pytest -q scripts/tests/test_portal_synthetic_storage_writer_fence.py`.

**MinIO result:** synthetic user could PUT before policy change. Detaching readwrite and attaching readonly then blocked PUT and DELETE while GET remained allowed. Administrator privileges were not revoked.

**PostgreSQL result:** synthetic app could INSERT before revoking table/sequence write grants. INSERT and UPDATE then failed, while SELECT succeeded. The privileged PostgreSQL owner could still INSERT after that: an explicit proof of a bypass.

Read-only production Docker inventory on October 23 identified seven known running containers and two credential-bearing storage client candidates, kipnerter-spatial-api-1 and kipnerter-spatial-worker-1. MinIO is also connected to the frontend network. No unexpected direct storage bind, Docker-control socket, host-network or privileged runtime candidates appeared. Network and environment-name presence do not prove effective permissions, absence of external accounts, or a write fence.

**Not a fence:** one role downgrade cannot exclude privileged database owners, MinIO administrators, other client keys, retries, workers or externally connected accounts. Source write barriers were not applied; no atomic multi-resource checkpoint, independent high-water custody, release authorization, production migration or login acceptance is proven. Every script result keeps `source_writes_fenced=false`, `safe_to_cutover=false` and `release_gate=NO_GO`.

Next production-gating work: enumerate all writer identities and paths with authority, design a single monotonic fence generation and deny stale credentials, exercise revocation and bypass negatives on disposable replicas, coordinate draining and backup custody, and separately prove rollback and real IdP browser acceptance. Never apply the synthetic commands to live databases merely because they passed.

Tracking: https://github.com/scottjoyner/kipnerter/issues/19 and https://github.com/scottjoyner/kipnerter/issues/50.