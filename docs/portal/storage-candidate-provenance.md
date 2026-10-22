# Staging-only object-storage candidate provenance (research)

**Observation date:** October 19, 2026, from x1-370. This is NOT a storage
migration, a MinIO data restore, a production release, or an authorization.

The deployed Compose image `minio/minio:latest` is unavailable from the research
host, and is still mutable and not independently pinned. The PostGIS configured
tag resolves to an independently checked registry manifest but is not runtime-tested.

This research probe inspects exactly two named, digest-pinned OCI candidates:

| Candidate | OCI index SHA-256 | linux/amd64 child manifest SHA-256 |
| --- | --- | --- |
| Silo (pgsty) | `635197cb9f36d01bee221d34d1c7d7960f6a95c48b0b6c01d99cd13bdae51a46` | `39aab3c365848e32aca7b76c5b57f86d1cbca02d7b8f24e1fd1feff9fedddae5` |
| MinIO AIStor | `107cf2014a9583c74c11e3cdbd6903d89c2244355886b89ce532f4ecae9c23f3` | `a94e1fe399bd050fe6d6148839597a4995350c0e62c9e83f0cec8b5630ed0a1e` |

Run `python3 scripts/portal_storage_candidate_witness.py --candidate silo`
(or `--candidate aistor`). Only Docker Buildx metadata inspection is used:
formatted root manifest, raw root bytes, and raw digest-pinned linux/amd64
child manifest. Hashes must match on every read. All errors fail closed.

No layers/config blobs are downloaded; no container is started; no volumes,
credentials, object stores, or databases are touched. A nonzero exit means
manifest-tree provenance is not currently available. The verifier does **not**
verify image signatures, builder identity, SBOM, runtime process architecture,
software safety, or legal rights to deploy the image.

## Release gates still open

1. Obtain explicit product/license and S3 compatibility review. Silo is a
   maintained *fork*, not an identical image; AIStor has a separate product
   and license. Neither can be silently swapped into production Compose.
2. Provision a separately tagged staging host with independent storage and
   identity boundaries. Do not reuse live PostGIS or MinIO named volumes.
3. Under approved change control, pull ONLY the reviewed immutable digest onto
   staging; verify full layers/config, signature/provenance and linux/amd64
   execution. Separate the candidate's compatibility evaluation from production.
4. Generate synthetic buckets/objects and PostGIS schema+rows, quiesce fixture
   writers, back them up, tamper with copies, reject corruption, and restore
   into *different* volumes; compare logical hashes, object SHA-256 and counts.
5. Have an independently administered reviewer inspect the actual restore
   outputs and sign the canonical receipt under externally controlled Ed25519
   keys. Verify it with `scripts/portal_restore_evidence.py` and a pinned
   topology fingerprint. Signatures alone are declarations, not observation.
6. Separately test Tailscale OIDC login, denied subjects, expiry/revocation,
   private observer ACL, exact-source cutover and live container+volume rollback.

The original `scripts/portal_image_custody.py` **remains unchanged** and the
production image is **not** altered. This candidate probe reports
`production_approved=false`, `restore_parity_verified=false` and
`independent_custody_verified=false` even when every manifest hash matches.
### October 19 follow-up: OCI descriptor consistency hardening

The research verifier now rejects an otherwise correctly hashed OCI index if its
selected linux/amd64 child descriptor declares a byte length different from
the fetched child manifest. It also requires syntactically qualified,
size-bounded config and layer descriptors with recognized runnable OCI/Docker
media types. The candidate child must have between 1 and 128 layers, each
with a valid SHA-256 digest, exact integer size and a supported layer media
type. A boolean size, negative/oversized size, unknown descriptor type,
missing config descriptor, or an empty-layer candidate fails closed even
when the surrounding index and child manifest SHA-256 digests match.

This intentionally stricter runnable-image candidate policy follows the
OCI image descriptor contract: a descriptor binds its target type, digest,
and byte size. The new boolean witness fields explicitly distinguish child
descriptor size validation, config descriptor shape validation and layer
descriptor shape validation. Config blobs and image layers are NOT downloaded
or hash-checked; their declared hashes cannot be treated as measured layer
integrity or execution readiness. No new image repositories are admitted,
and no candidate is authorized for production.

Both fixed candidate endpoints were rechecked on October 19, 2026 using
read-only Buildx index/child-manifest queries after the new validator was
enabled. Both reported valid child-byte sizes and structurally valid
config and layer descriptors with status 'immutable_manifest_tree_verified'.
The reported research child digests remained the ones listed above. Both
outputs retained false values for architecture runtime, restore parity,
independent custody and production approval.
