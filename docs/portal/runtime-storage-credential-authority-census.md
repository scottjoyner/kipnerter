# Verified runtime storage-credential authority census — 2026-10-23

**Release classification: HOLD_PRIVILEGED_STORAGE_CLIENT_AUTHORITY / NO_GO.**

## Physical production finding

The exact source-controlled read-only Docker topology inspector and sanitized authority checker were streamed over existing authenticated non-root Tailnet SSH to `kipnerter-prod-01`. **No values from Docker container environments, SQL role names, URLs, passwords, token strings, database rows or object bodies were printed or transmitted to the operator.** The comparison took place in the production host's Python process and returned only counts and boolean classifications.

**Live runtime result:** two configured API/worker bindings; **two of two** reference privileged PostgreSQL login authority, and both use the same PostgreSQL login. **Two of two** match MinIO's configured root access identifier **and the complete corresponding root secret**. One PostgreSQL login role exists and is a superuser. Neither production PostgreSQL nor MinIO had writer fencing. This confirms the earlier checked-in `compose.spatial.yml` anchor observation as an **actual running-container credential equality**, not merely a configuration hypothesis.

The census does **not** prove that every connected session belongs to one of these services, that all S3 policies have been inventoried, or that network isolation excludes external/old credentials. It grants **no** permission to rotate production passwords or stop/redeploy services.

## Source and repeatability

The safe-default `scripts/portal_production_storage_authority_readonly.py` runs no Docker or SQL without explicit `--inspect-live` and the pinned production hostname; it refuses Docker target overrides. It checks the exact running storage-image identities, seven expected container instances and current writer-surface topology, then compares the two app DSN login names with a bounded PostgreSQL login-role SELECT and the app S3 root-credential pair with its running MinIO environment. All sensitive strings remain inside the remote Python process. Malformed/ambiguous results fail closed. The source is built from the separately reviewed `portal_production_writer_surface_readonly.py` and this checker by `portal_storage_authority_bundle.py`; no production source-file installation is needed.

The source-only bundle defaults to `DRY_RUN_NO_SSH_OR_DOCKER`. On an approved operator host, explicit emission could be piped into the approved Tailnet SSH session:
```bash
python3 scripts/portal_storage_authority_bundle.py --emit-remote-source \
  | ssh -oBatchMode=yes -oStrictHostKeyChecking=yes kipnerter@100.82.144.33 'python3 - --inspect-live'
```
**No production credential data appears in that command**, and the output is bounded status/role-count booleans only. No production modifications or identity changes have been made.

## Next release gates

Tracked in [P0 #88](https://github.com/scottjoyner/kipnerter/issues/88): distinct non-superuser API and worker PostgreSQL roles with real workload/schema/extension/worker/migration tests; distinct non-root, least-privileged S3 accounts and policies, with secure credential custody; reversible deployment and rollback; full external/admin/queue writer admission and revocation; and independently witnessed atomic multi-store checkpoint. Existing private OIDC enrollment/browser acceptance and legacy OCI image recovery remain separate gates.

The merged synthetic service-role experiments in [PR #90](https://github.com/scottjoyner/kipnerter/pull/90) demonstrate isolation only on invented schemas, not that the production ORM and background workers can run under those restrictions.

**Invariant:** `postgres_writes_fenced=false`, `minio_writes_fenced=false`, `safe_to_cutover=false`, `release_gate=NO_GO`.
