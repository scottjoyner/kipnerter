# Legacy web/API private launch-settings custody (ONE SHOT, release HOLD)

The original legacy `kipnerter-api-1` and `kipnerter-web-1` are still running,
but their exact OCI image digests are uncached. Private source and rootfs tar
archives already exist, with SHA-256 receipts. Those files do **not** preserve
original entrypoint, command, environment, health checks or Docker runtime
configuration, and they do **not** prove a working rollback.

The protected one-shot `ios17-legacy-launch-metadata-private-once.yml` job
requires an owner-authored merge commit containing
`[ios17-legacy-launch-metadata-once]`. It uses the production environment,
scoped CI Tailnet credentials, strictly tagged production target selection,
and the preexisting non-root `kipnerter` account.

The script verifies private owner-only 0700 custody, the existing old rootfs
receipt and both allowlisted archived rootfs files. It reads ONLY the two
exact old running container IDs via `docker inspect`, verifies the original
image SHA-256 identities, Compose project, stable start times, and no mounts.
Only allowlisted field names, types, counts and SHA-256 fingerprints are retained, never raw command, network, health-check or environment values. Before
saving, it checks that neither live configuration changed during inspection.

**Privacy:** Docker `Config.Env` may include passwords or API tokens; this verifier discards their values and retains only environment variable names. All other launch settings are hashed structural fingerprints. The metadata is create-only, mode 0600, on the production host's
existing private backup directory. It is *never printed*, sent to a GitHub
Actions artifact, pasted into a ticket, exposed via telemetry or copied to
another host. The separate private 0600 receipt contains only bounded sizes,
SHA-256 hashes, original rootfs receipt binding, counts and explicit NO-GO
flags. Any incomplete or existing target blocks repeat execution.

This code never runs `docker export`, `docker create`, `docker run`,
`docker commit`, `docker pull`, rewrites tags, alters networks, changes
environment values, restarts live containers, touches persistent volumes,
or enables public ingress. All outcomes explicitly set
`runnable_rollback_verified=false`,
`independent_admin_custody_verified=false` and `safe_to_cutover=false`.

A **separate approved** isolated off-host restore/rehearsal must demonstrate
legacy app/API health and functional behavior before production cutover.
Stateful PostGIS/MinIO consistency and real browser Tailscale OIDC also
remain independent hard release gates.
