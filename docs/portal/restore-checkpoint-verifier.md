# Independent-key synthetic restore checkpoint (offline research)

This verifier extends `portal_restore_evidence.py` with a third, distinct
Ed25519 signing identity bound to the **same** synthetic Postgres/MinIO restore
receipt. It is read-only and does not authenticate real restore execution,
independent administration, or production release authorization.

## Contract

`scripts/portal_restore_checkpoint.py` accepts four private JSON inputs:
the original executor-and-reviewer-signed synthetic receipt, its separately
pinned two-role public-key trust root, a signed observer checkpoint, and the
observer's *separately supplied* public-key trust root.

The verifier requires independently supplied expected release SHA and topology
SHA-256, not merely two self-consistent signed documents. The observer signs
canonical JSON containing the exact 40-hex release SHA,
topology fingerprint, fixture nonce, existing signed-claim SHA-256, a
timezone-aware timestamp, a positive **sequence >= 2**, and a 64-hex previous
checkpoint digest. The supplied expected sequence and prior checkpoint digest
must match exactly. The observer key must have a different SHA-256/SPKI identity
from both receipt roles. Its Ed25519 signature is verified over the canonical
checkpoint payload. The exported next checkpoint hash covers the **complete
signed envelope**, not just its payload. Inputs must be private owner-controlled
regular files, with strict JSON schema and no duplicate keys.

Example (illustrative only; provide real private, independently controlled
files and an external checkpoint reference):

    python3 scripts/portal_restore_checkpoint.py \
      --receipt /private/receipt.json \
      --external-role-trust /private/role-trust.json \
      --checkpoint /private/checkpoint.json \
      --external-observer-trust /private/observer-trust.json \
      --expected-sequence 12 \
      --expected-prior-sha256 <64-lowercase-hex> \
      --expected-release-sha <40-lowercase-hex> \
      --expected-topology-sha256 <64-lowercase-hex>

A passing result means that **three distinct pinned public keys signed matching
synthetic statements**, and the supplied checkpoint extends the
operator-selected prior digest at the requested sequence. It does *not* prove
that a custodian published this checkpoint to an append-only, rollback-resistant
external store. Anyone controlling all trust files and all three keys may forge
the entire series, and replaying the same signed checkpoint with the same
untrusted expected arguments can still pass.

Consequently, `durable_external_high_water_verified`,
`observer_administrative_custody_verified`,
`restore_operations_independently_observed`, and
`production_recovery_approved` **always remain false**. These cannot be
changed by a signature or a script flag. Real production admission requires
independent custody with externally persisted monotonic checkpoints, tested
replay rejection, direct verification of restored Postgres and object data,
operator-approved storage images, and an isolated staging rehearsal.

The five initial synthetic tests validate valid signatures, receipt/nonce/
topology/sequence/chain mismatch rejection, observer key reuse rejection,
forgeries, stale timestamps and private-file/duplicate-field checks. No image
layers, database tables, storage volumes or fleet machines were accessed.
