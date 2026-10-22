# Multi-checkpoint synthetic restore chain — offline qualification

The single-checkpoint verifier in `portal_restore_checkpoint.py` can verify a
third distinct Ed25519 signature tied to an executor/reviewer-signed synthetic
Postgres/MinIO receipt. But the same signed checkpoint can be replayed if an
attacker supplies the expected sequence and prior hash. This follow-on
**read-only** verifier can check a bounded, contiguous series against an
operator-supplied **start and end** anchor without accessing Docker, SSH,
volumes, databases, an object store, or release approval secrets.

## Contract

`python3 scripts/portal_restore_chain.py` requires four **separate private,
operator-owned, non-symlink JSON files**:

- `--chain`: version-1 `synthetic_restore_checkpoint_chain` with 2–16 ordered
  entries, each containing exactly a signed receipt and observer checkpoint.
- `--external-anchor`: version-1 `operator_pinned_synthetic_restore_chain`
  with immutable expected starting sequence/previous checkpoint SHA-256,
  ending sequence/checkpoint SHA-256, exact release commit SHA, and topology
  SHA-256. This file **must be supplied independently from the chain**. A
  self-generated anchor does not establish rollback protection.
- `--external-role-trust`: the pinned executor and independent reviewer
  public-key identities used for signed synthetic receipts.
- `--external-observer-trust`: a third distinct pinned observer public key.

For every entry, the verifier checks the complete two-role receipt signatures,
third-role Ed25519 checkpoint signature, exact release/topology/nonce binding,
next contiguous sequence and preceding **signed envelope** SHA-256, freshness,
strictly increasing receipt and checkpoint timestamps, nonce uniqueness, and
unchanged image identities across the series. The last checkpoint's full
signed-envelope hash **must equal the independently supplied ending hash**.
The number of checkpoint entries must equal the externally supplied sequence
span. Duplicate JSON keys, symlinks, non-private files, same-inode trust inputs,
missing/truncated/forked entries, altered signatures and replayed nonces fail
closed. Read size is bounded; raw signatures, trust keys and credentials never
appear in the success report.

```
python3 scripts/portal_restore_chain.py \
  --chain /private/synthetic-checkpoints.json \
  --external-anchor /separate-custody/start-and-end-anchor.json \
  --external-role-trust /private/role-public-keys.json \
  --external-observer-trust /private/observer-public-key.json
```

A **passing result is only a cryptographic chain consistency result** for
synthetic receipt statements. It cannot prove any of the following, which
are reported as `false` without exception:

- Independent administrative or physical control of the starting/ending anchors.
- Durable external high-water recording or rollback-resistant publication.
- Real observed PostgreSQL/MinIO writes, backup restoration or data equivalence.
- Authorization to merge, deploy, rotate credentials, admit fleet models or
  approve production recovery.

An attacker holding all three signing keys and the external anchor file can
forge a wholly new consistent chain. Validating a previously trusted high
water across time requires a separately administered append-only custodian and
an actual high-water check, outside this CLI's authority. **Do not** wire its
success status to the production approval-SHA secrets.

The current environment also lacks a separately tagged staging host and a
verified MinIO image. Existing storage-topology checks and signed synthetic
receipts remain prerequisites, not release authorization. No Docker images
were downloaded and no volumes, processes or production services were touched.

## Oct 19 — descriptor-bound private-input hardening

The standalone executor/reviewer receipt verifier and third-role checkpoint
verifier now load JSON from the **same open file descriptor** whose regular-file
status, owner, mode and byte limit were checked. They reject symlinks,
world/group-readable input, FIFOs and other special files, oversized or empty
content, and duplicate JSON keys. The earlier path-stat-then-read code could
read a different pathname target if it was swapped between the two operations.
A deterministic regression test swaps the pathname after open and verifies
that only the original inode's bytes are accepted.

The multi-checkpoint verifier already opened private files with no-follow.
It now also compares the **opened descriptor's device/inode identities** for
its chain, external anchor and two trust roots, rather than stat'ing each
pathname separately before reading. A hardlinked duplicate anchor is rejected.

These checks protect against common local pathname substitution mistakes.
They do **not** establish immutable files, independently administered trust,
replay-resistant high-water storage, actual Postgres/MinIO restoration, or a
production release approval. No stateful services or volumes were accessed.
