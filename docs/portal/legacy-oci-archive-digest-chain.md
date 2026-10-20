# Offline Docker/OCI archive identity-chain qualification — no extraction or import

## Purpose and current limitation

[Kipnerter issue #50](https://github.com/scottjoyner/kipnerter/issues/50)
remains a production **NO-GO**: neither exact original web nor original
API OCI image is available as a verified runnable rollback artifact.
The original live image IDs are pinned by the Oct 20 private launch
receipt, and two Docker rootfs exports plus a source archive are retained
privately. These are **NOT** Docker image archives: rootfs exports omit
the layer/config/entrypoint chain, while source does not establish a
bit-equivalent original build. Do not feed them to this verifier.

The new `scripts/portal_legacy_oci_archive_verify.py` accepts an
existing, **operator-approved Docker `save` OCI archive** on standard
input. It neither calls Docker nor contacts a registry; it streams
archive members without extracting, importing, retaining, executing,
printing or uploading the archive. It enforces bounded counts and sizes,
rejects nonregular, duplicate and unsafe member paths, verifies every
included `blobs/sha256/*` blob against its actual bytes, parses
`index.json` through the root image index to exactly one Linux/amd64
image manifest, verifies config/manifest/layer content hashes and declared
sizes, validates the config's rootfs diffID inventory shape, and
cross-checks the compatibility `manifest.json` layer/config references.
The pinned historical identity must match **either** the digest of the
root OCI image index or the config blob (Docker stores differ).

**Evidence boundary:** this revision additionally computes and verifies
uncompressed rootfs `diff_ids` for raw and gzip-compressed layers. To avoid
claiming unverified content, zstd-only layers are rejected (HOLD) until a
similarly bounded streaming zstd decoder is implemented and tested; corrupt
gzip bodies, mismatched media types, truncated compressed streams, trailing
bytes and decompression-limit violations are rejected. Verification computes
hashes **without unpacking any filesystem content onto disk**, but does
not prove that a Linux runtime will safely apply those layers.

Sparse OCI exports can
omit other platforms even when the original index lists them, so
`full_multiplatform_archive_verified=false`. An OCI digest chain is not
independent source provenance, authenticated custody, a runnable import,
a health/auth/route acceptance test or an actual rollback after failure.

## Actual offline physical test — October 20, 2026

The x1-370 Docker daemon already cached a *nonproduction research image*
`python:3.12-slim`; no image download/build was performed. An
ephemeral `docker save` pipe fed the verifier directly:

```bash
set -o pipefail
docker save python:3.12-slim | python3 \
  scripts/portal_legacy_oci_archive_verify.py \
  --research-fixture-id sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
```

The stream returned `RESEARCH_IMAGE_NOT_LEGACY` (exit 0) with one
Linux/amd64 manifest, four layer blobs and config/image index identity
matching its pre-observed research image ID, with **no extraction** and
all rollback/cutover flags false. A second physical research run after
the uncompressed-diffID enhancement additionally verified all **four
uncompressed `diff_ids`** against the cached image's OCI config, without
importing or extracting the image. The same stream still fails closed
(exit 2) when falsely asserted to be the historical Kipnerter API.

A second attempt streamed **the same research image** but used
`--role legacy-api`; the verifier rejected this fake original-API
identity with `HOLD`, exit 2. No original legacy image was found or
changed, no production connection used, and no secret values printed.

## Privately retained original-image candidates

The only legitimate original-image test requires a separately approved
Docker image archive, *not* a `docker export` container-rootfs tar or
mutable tag. Under an authorized owner-controlled isolated environment,
stream the candidate archive from a private 0600 file into the verifier:

```bash
# Example ONLY once a verified private Docker image archive exists:
python3 scripts/portal_legacy_oci_archive_verify.py \
  --role legacy-api < /private/approved-old-api-image.tar
python3 scripts/portal_legacy_oci_archive_verify.py \
  --role legacy-web < /private/approved-old-web-image.tar
```

Never put the image archive, source tarball, Docker image config (may
contain environment variables), registry credentials, or private layer
names into GitHub workflow artifacts or logs. The verifier outputs only
aggregate booleans/counts, never raw OCI config. Layer bytes, decoded
gzip bytes, tar member file names and even the image ID never appear
in the JSON response. Its success is an
**archive-integrity candidate**, and its status is always
`OCI_DIGEST_TREE_VERIFIED_NOT_RUNNABLE` with
`safe_to_cutover=false` and `launch_behavior_verified=false`.

There is currently no such verified original-image archive for either
legacy service. If derived from rootfs/source instead, label it as a
**different reconstructed image** and require private independent
review of embedded secrets and configuration provenance.

## Follow-on gates

Keep the original production containers running. Independently retain
the reviewed image archive/config/layer provenance; prove executable
web+API restarts and old health/auth/routes in isolated staging without
live mounts/public ports; induce failure and prove reversible rollback;
then verify real PostgreSQL and MinIO recovery, independent custody,
production OIDC and release approvals. The latest validated hosted
CI for the preceding commit is
[39451405683](https://github.com/scottjoyner/kipnerter/actions/runs/39451405683).
CI for subsequent commits must be checked again.
