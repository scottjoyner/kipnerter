# Local AIStor runtime qualification: immutable metadata is not restoration

On October 20, 2026, a **pre-cached**, exact-image-ID MinIO AIStor
candidate on `x1-370` was tested in a disposable isolated container.
This is a research candidate, not the old production MinIO image.

Previously `portal_storage_candidate_witness.py` could verify OCI index
and child-manifest bytes, but it did **not** run an S3 server or prove
PostgreSQL/MinIO backup recovery. That distinction remains important.

## Physical observation

The locally cached `quay.io/minio/aistor/minio:RELEASE.2026-09-19T17-05-25Z`
had image ID
`sha256:107cf2014a9583c74c11e3cdbd6903d89c2244355886b89ce532f4ecae9c23f3`.

A detached, disposable, bounded Docker container used `--network none`,
`--read-only`, synthetic temporary credentials, `--tmpfs /data` and
`--tmpfs /tmp`; no host volume or production files were mounted, no
ports were published, and the container was removed afterward.

Its local `/minio/health/ready` HTTP endpoint returned **503**.
The diagnostic log classified the failure as **no valid AIStor license**,
with S3 operations denied in offline mode. No license was installed and
none is implicitly approved as a remediation. The candidate cannot be
used for an S3 restoration rehearsal in this state.

## Repeatable, narrowly scoped preflight

```sh
python3 scripts/portal_storage_runtime_probe.py
```

The source-controlled script checks the **already locally cached exact
image ID** before any Docker start. It does not pull or build, runs the
fixed image only in a uniquely named, non-networked, private tmpfs
container, issues one bounded localhost readiness observation, then
removes the container. A 503 or failed launch exits 2 (HOLD). Even
HTTP 200 would only produce `HTTP_READY_ONLY` with an explicit
`synthetic_s3_roundtrip_verified=false`. A failed cleanup invalidates
a positive observation.

The script deliberately never sets these to true:
`minio_backup_restoration_verified`,
`original_production_minio_image_verified`,
`independent_custody_verified`, or
`production_recovery_approved`.

This probe must not be wired into release-secret or production approval
generation. A separately reviewed compatible and runnable MinIO image,
approved backup custody, exact data restoration to isolated staging,
object PUT/GET inventory/content comparison and independent operator
sign-off remain required. Postgres synthetic fixture restoration is not
proof of the production database restore either.

The unit tests cover immutable-image substitution, AIStor 503,
unexpected responses, bounded attempts, failed container start,
failed cleanup, and the hard distinction between HTTP readiness and
verified S3 restoration. No production images or storage were changed.
