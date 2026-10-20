# Previous live web/API image: read-only rootfs preservation preflight

The production rollback image-retention run found that the two **running**
legacy containers' exact original OCI images are no longer cached. The local
tags `kipnerter-api` and `kipnerter-web` now resolve to **different** images
and MUST NOT be presented as rollback images for those running containers.

`scripts/portal_legacy_rootfs_export_preflight.py` checks only allowlisted
Docker scalar metadata. It pins the two exact image IDs, verifies the Compose
project and running state, requires zero container mounts, checks container
rootfs/writable layer bounds, confirms the originals remain uncached and the
tags point elsewhere, and applies a conservative disk-headroom threshold.

Run with read-only production credentials; its exit code 0 means **only that
a rootfs export is a plausible preservation candidate**, not that an actual
export or recovery was performed. The JSON receipt deliberately keeps
`candidate_rootfs_export_created=false`,
`rootfs_export_equivalent_to_old_oci_image=false`,
`recovered_container_launch_metadata=false`,
`isolated_rollback_test_passed=false` and
`safe_to_cutover=false`. Error paths return HOLD without changing Docker.

A container filesystem export (if separately authorized later) does NOT
preserve OCI layer identities, image manifests, build provenance, launch
environment, Docker metadata, network settings, volumes, or external service
state. A live filesystem may change during export. Even though these two
current containers have no mounts, rootfs preservation cannot be promoted
to a runnable rollback without an isolated boot test and a separately
verified release plan. An export could contain sensitive baked-in files and
must remain privately controlled and independently reviewed.

Read-only qualification on October 19, 2026 observed two exact live roles,
rootfs combined <=716 MiB, writable layers <=4 MiB, >=68 GiB production
free capacity and no mounts. **No exports, images, new containers, tag
rewrites or production restarts were created.** This finding does not waive
real Tailscale OIDC acceptance, staging role/DNS, independent state backup,
or production cutover approval.
