# Fourth-key high-water receipt — offline research verification

The chain verifier already checks multiple synthetic signed Postgres/MinIO
restore receipts against an externally selected start/end pair. The read-only
`portal_restore_high_water.py` additionally checks the **whole chain tip**
against a **fourth, separately signed** custodian receipt. It never writes to
an append-only log, Docker, SSH, a database, MinIO or production release state.

## Inputs

All six JSON files must be regular, owner-private, non-symlink files with
different opened inode identities. JSON duplicate keys, unexpected fields,
oversize input and changed signing identities fail closed.

1. `--chain`: the bounded existing synthetic checkpoint chain.
2. `--external-anchor`: exact release/topology and chain start/end pins.
3. `--external-role-trust`: pinned executor + reviewer public keys.
4. `--external-observer-trust`: distinct third-role observer key.
5. `--signed-high-water`: an envelope containing `payload` and
   `custodian_signature` of the canonical payload.
6. `--external-custodian-trust`: a fourth distinct pinned Ed25519 public key,
   supplied outside the candidate chain.

Signed `payload` has EXACT fields: `version=1`,
`scope=synthetic_restore_custodian_high_water`, `end_sequence`,
`end_sha256`, `release_sha`, `topology_sha256`, `recorded_at` with
timezone. The sequence and digest **must equal** the verified chain tip.
A shorter chain, a fork at the same sequence or an unanchored future sequence
is rejected. The receipt time must not precede the final signed checkpoint.
The high-water envelope's SHA-256 is reported without printing signatures.

```sh
python3 scripts/portal_restore_high_water.py \
  --chain /private/chain.json \
  --external-anchor /private/anchor.json \
  --external-role-trust /private/roles.json \
  --external-observer-trust /private/observer.json \
  --signed-high-water /external-custodian/signed-tip.json \
  --external-custodian-trust /external-custodian/public-trust.json
```

## What is proven and what remains NO-GO

**Proven only when all supplied inputs are authentic:** matching synthetic
chain tip and custodian-signed record, with four *distinct public-key
identities*. Removing the latest record while retaining the genuine custodian
tip, substituting a different tip with the same sequence, or forging the
fourth-role signature fails verification.

**Not proven:** the custodian is externally administered; the signer has a
separate hardware/credential boundary; signing and publication happen on each
accepted state change; the high-water record is immutable, durable and
monotonic; the independently selected custodian trust file is not replayed;
Postgres tables or MinIO S3 objects were really restored. If the same
adversary can roll back **both** this signed tip and the chain (or change the
custodian trust root), this checker cannot detect that rollback. A valid
signature does not make its storage append-only.

For actual admission, build an authenticated separately administered
witness service with atomic compare-and-append, non-rewritable high-water
publication and independent trust distribution. Verify old-state/revocation/
fork attempts against that service **online**, rehearse isolated restore from
immutable source images to new database/object resources, compare table and
object content digests, then require independent operator sign-off.

The tool deliberately reports
`independent_custodian_control_verified=false`,
`rollback_resistant_persistence_verified=false`,
`durable_external_high_water_verified=false`,
`real_restore_verified=false`, and
`production_recovery_approved=false`. No CI success may be used to set the
release-approval SHA environment gates.

## Negative controls

The test suite covers exact-match synthetic success; shortened/advanced/forked
tips; changed release/topology; forged signature; wrong or reused keys;
future timestamps; swapped file paths via symlinks, same-inode hardlinks,
world-readable files, duplicate JSON fields and blocking FIFOs.
