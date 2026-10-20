# Synthetic network-disabled rootfs import/boot rehearsal

This is a **non-production-only** Docker import and boot rehearsal for the
Kipnerter legacy API/web recovery process. It uses freshly generated
`synthetic-api-restore-proof` and `synthetic-web-restore-proof` BusyBox
filesystems. It never reads or transfers a private legacy rootfs tar or
launch-metadata receipt, accesses a database, starts real application code,
or changes a production container.

On a **verified NON-production** host with a local statically linked
`/bin/busybox`, a working Docker daemon, and an explicit operator
acknowledgement:

```sh
python3 scripts/portal_synthetic_rootfs_restore_probe.py \
    --run-synthetic --nonproduction-host-ack
```

The opt-in import creates two randomized local-only image tags. It tests
each in a named `--rm` container with `--network=none`, `--read-only`,
`--cap-drop=ALL`, `--security-opt=no-new-privileges`,
`--pids-limit=32`, `--memory=128m`, `--cpus=0.25`, no mounts,
nonroot UID/GID and **no ports or Docker pulls**. It verifies the proof
contents and deletes its own imported tags when completed. An occupied
image tag must never be deleted.

On x1-370 the synthetic API and web archives were generated, imported,
executed and removed successfully. Tests reject bad members, missing
acknowledgment, wrong fixture and unintended deletion of an existing tag.
Every result explicitly reports:

- `actual_legacy_rootfs_accessed=false`
- `legacy_functional_rollback_proven=false`
- `original_images_recovered=false`
- `public_deployment_authorized=false`

This does **not** prove that the original `kipnerter-api-1` or
`kipnerter-web-1` will boot. The originals' OCI manifests, entrypoints,
secret values and functional state are not recovered by the fixture.
Restoring genuine evidence requires independent authority, a separately
authorized isolated host, protected secret custody and acceptance tests.
The protected production API/web containers and public site are untouched.
