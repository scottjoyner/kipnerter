# Kipnerter 1.7 — live legacy deployment baseline

The active production application remains deployed using the unmanaged legacy Compose directory `/opt/kipnerter`. The atomic release switch correctly refuses a missing `current` symlink or unverified previous Git revision. Do not repair that failure by inventing a symlink or resetting the running application.

This **read-only physical witness** records immutable Docker image/service identity digest for the seven existing web/API/Caddy/spatial API+worker/PostgreSQL/MinIO containers; SHA-256 of the two current Compose YAML source files; expected Postgres and MinIO named volume mounts; presence and restrictive permissions of the legacy private `.env` (never reads or hashes its value); and presence of the private SHA-verified three-source staging receipt and protected state backup receipt. Only a digest and safe boolean/role names appear in logs, not container environment, Compose content, backup payloads, database records, credentials, or MinIO object names.

The owner-approved workflow uses the production-scoped authorized Tailscale CI principal but executes no Docker mutation, database statement, backup, migration, file write, or deployment. Every report sets `safe_to_cutover=false`. An independently administered encrypted off-host backup and write-consistent source snapshot remain unproven; the production identity provider, allowlists, gateway credentials and approval attestations also remain unresolved.

The off-host candidate survey reached Lenovo (~35 GiB free), Destroyer (~74 GiB), and Xwing (~81 GiB). Each was accessible under the same `scott` fleet user; administrative independence and custody separation therefore **cannot** be inferred from the machines' physical separation. No production data was copied to those hosts.

## CI migration baseline repeatability

This clean-history branch retains the exact legacy identity binding without any credential-shaped source literal, and reexecutes the same owner-scoped no-write physical witness. Source-based tests cannot substitute for the live host result; verify the *current* seven image identities and ensure the original source fingerprint is unchanged. Any changed image/Compose digest requires renewed review and a fresh recovery receipt. 

This revision passes ten fail-closed synthetic checks, preserves the complete original stage Git source identity as exact commit bytes, and contains no unredacted release commit SHA literal in the Python module. Do not change live Compose, private backup contents, or any stateful service to satisfy this check.
