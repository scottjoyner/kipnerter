# Private legacy rootfs preservation — deliberately not an OCI rollback

This one-shot job is intended to retain additional *forensic* filesystem
evidence for the two original live legacy API/web containers. Their original
OCI image IDs are absent from the Docker image cache. Current local image
tags point to **different images**.

The guarded workflow `ios17-legacy-rootfs-private-once.yml` only triggers
on an owner-authored commit whose message contains
`[ios17-legacy-rootfs-copy-once]`. It uses the protected production GitHub
environment, the unique production Tailscale tag and normal Tailscale SSH
to the `kipnerter` account. It cannot contact a different host identity.

The script checks the **full pinned original image identities**, running
state, unchanged startup timestamps, Compose project, no mounts, private
owner-only 0700 custody directory, previously verified source receipt,
different current image tags and free disk capacity. Each export is bounded
to 2 GiB. Docker export streams go directly into *private 0600 files* and
never into GitHub logs or Actions artifacts. It never asks for production
environment values or emits archived filenames. A digest receipt only
appears after both streams validate and both containers remain running
from their original identities. It refuses to overwrite any completed
archive or run if an incomplete private export is present.

**Important limitations:** A running container may mutate its filesystem
during `docker export`. A rootfs tar does not preserve original OCI image
layers, metadata, entrypoint, env, volumes, production registry provenance
or transactional snapshot consistency. It may contain sensitive baked-in
files and must never be sent as public CI artifacts. The script **does not
create a runnable original image or prove rollback**. Its receipt always
sets `runnable_rollback_verified=false` and `safe_to_cutover=false`.

Separate owner-approved steps would still be required to test a fully
isolated restored legacy API/web instance against known configuration;
prove private key custody, stateful database and object-store restores,
complete OIDC browser sign-in/expiry/deny, staging DNS/TLS, and an actual
reversible public cutover. The default public website is unchanged.
