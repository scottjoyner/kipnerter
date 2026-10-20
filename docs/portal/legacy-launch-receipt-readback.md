# Independent code-path verification of legacy launch receipt (read-only)

The prior owner-only preservation workflow created a redacted, 0600
launch-structure evidence file and digest receipt on the production host.
It did not recreate the original OCI image manifests or verify a runnable
rollback. This verifier follows a **separate code path** from the writer.

The owner-gated `ios17-legacy-launch-receipt-verify.yml` workflow runs only
when an owner-authored protected recovery-branch commit includes
`[ios17-legacy-launch-verify-once]`. It selects the unique
`tag:kipnerter-prod` Tailnet peer through the existing deny-by-default
selection helper. An ephemeral CI Tailnet identity reads the private evidence
through the regular `kipnerter` account. No source or evidence bytes are
downloaded, logged, uploaded as Actions artifacts, or sent to another node.

Checks include:
- Owner, type and mode of the private 0700 custody directory and 0600 files.
- Old rootfs receipt schema, both original pinned image identities and
  exact archive lengths, recomputing the full SHA-256 for both rootfs tars.
- One redacted launch file and its separate receipt; duplicate JSON keys,
  exact expected schema, exact SHA-256 and length, original rootfs binding.
- Strictly allowlisted structural fingerprint fields, environment **variable
  names only**, no raw command or launch environment, and NO-GO flags.
- Read-only Docker scalar inspection of both original running container IDs,
  startup timestamps and zero mounted volumes, without exposing raw
  `docker inspect` environment values.

All outputs are bounded JSON booleans/counts. A success does not establish
independent administrative key custody, original OCI layer recovery,
a verified isolated restart, database/object store write fencing, or a
production release. The same operator and production host still control
both copies. The verifier deliberately has no Docker write commands,
container starts/stops, ingress modifications, or storage changes.
