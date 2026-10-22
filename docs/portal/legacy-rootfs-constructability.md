# Legacy web/API rollback: rootfs constructability audit (research-only)

## Why this matters

The October 20 [private launch receipt verification run
39432194703](https://github.com/scottjoyner/kipnerter/actions/runs/39432194703)
reported `archived_rootfs_count=2`, `redacted_launch_roles=2`,
`live_identity_checked=true`, but also
`old_oci_images_recovered=false`, `runnable_rollback=false` and
`safe_to_cutover=false`. That is a meaningful preservation milestone,
but raw `docker export` root filesystems do not carry original
`ENTRYPOINT`, `CMD`, user, runtime environment, image history/layer
chain or independently witnessed execution equivalence.

The original live web/API immutable IDs are specifically missing from
the production Docker image store (issue #50). Redacted
launch-configuration *fingerprints* cannot be substituted for the actual
original configuration values. The private rootfs exports may also
contain baked-in sensitive files. **Never upload them to GitHub or a
public artifact. Never rebuild or import them automatically.**

## New source-controlled, read-only audit

`scripts/portal_legacy_rootfs_constructability.py` verifies the two
known rootfs-export archive names and known original image IDs from a
private schema-1 receipt. It opens the 0700 custody folder and each
0600 file via pinned read-only descriptors (no-follow/nonblocking,
owner/single-link checks). For both tarballs it verifies declared
size, SHA-256 and member count. It parses tar *headers* and classifies
link/special nodes, potentially sensitive path classes and setuid bits.
Duplicate, absolute and traversal paths are rejected. No tar bytes
are extracted, no Docker commands run and no raw path names, file
contents, image keys or receipt hashes are emitted. Archive size is
limited to 2 GiB each; member count to 200,000 each. The audit is
entirely local to wherever its authorized operator invokes it.

The scope is **not** an independently administered custody witness and
does **not** verify the authenticity of an attacker-replaceable receipt.
A privileged actor who can rewrite a receipt and both rootfs archives
can still fool a matching local hash. Furthermore, while a pinned FD
closes pathname substitution, it is not a snapshot if a privileged actor
mutates the open inode concurrently. The summary remains evidence-only.

Running it **only under a separately authorized owner-private
staging/CI identity**:

```sh
python3 scripts/portal_legacy_rootfs_constructability.py \
  --private-custody-dir /home/kipnerter/.local/state/kipnerter-release/state-backups
```

No real production archive was read or transmitted during local
development. The production Tailscale SSH host continues to require an
additional owner identity check; do not bypass it.

An uncorrupted synthetic archive produces `METADATA_ONLY_HOLD`.
This is an *audit completion* label, never an OCI recovery acceptance:
`oci_config_and_layer_chain_restored=false`,
`runnable_rollback_verified=false`,
`independent_admin_custody_verified=false`, and
`safe_to_cutover=false` regardless of the number of validated tar
members. Corruption or malformed inputs produce `HOLD` with exit 2.

## Runnable rollback exit conditions (not yet met)

1. Independently review and pin **recoverable runnable image** artifacts
   corresponding to both original web and gateway versions. If
   reconstructing from raw rootfs, treat the result as a **new derived
   artifact, not the original image**, and require privileged operator
   review for embedded secrets, config provenance, entrypoint/user and
   network policy. No production `docker import` or `docker commit`
   should occur as part of this preflight.
2. Rehearse candidate images only in isolated, owner-approved staging,
   no production host mounts, no production credentials, no public ports
   and no access to live state. Prove old health/auth/route behavior,
   restart durability and post-failure rollback.
3. Retain a sealed, immutable, independently administered digest/receipt
   with exact release SHA, image IDs, independent operator approval and
   separately verified Postgres/MinIO recovery. Hosted exact-head CI
   must also succeed.
4. Preserve both original live containers until these gates pass.

Ten synthetic-only negative tests cover normal metadata audit,
wrong image/receipt role/count/digest/size, duplicate JSON and tar paths,
traversal, special file controls, owner-only files and folders,
sensitive-name redaction and rejection of unearned release claims.
Production deployment and `/chat` publication remain **HOLD**.
