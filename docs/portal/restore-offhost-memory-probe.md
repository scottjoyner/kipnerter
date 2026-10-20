# Off-host, memory-only synthetic checkpoint verifier — October 20, 2026

This operator-facing probe extends the local four-key signed high-water receipt
and local JSONL custodian research ledger with a second-physical-host readback.
It is **not** an independent, durable high-water service and is not a
production release gate.

## Safe scope

Only a **synthetic** local checkpoint ledger is allowed. Inputs contain no
passwords, private signing keys, backup data, database rows, object contents,
trace bodies or model routes. The source is read through a private-file inode
with a shared read lock. The caller must supply a separately retained
64-hex digest to prevent self-pinning. The remote side receives only this
synthetic ledger, expected digest and freshly random 256-bit challenge.

`scripts/portal_restore_offhost_probe.py` hard-codes the existing
host-key-verified SSH alias `lenovo`; there is no arbitrary-host or command
execution interface. SSH uses BatchMode, StrictHostKeyChecking, no TTY and
no port forwards; the remote Python stdlib verification script executes
from memory using `python3 -c`. It writes no files and doesn't install
services. It independently canonicalizes and hashes every synthetic JSONL
record, checks required fields, duplicate keys, sequence adjacency,
previous-checkpoint continuity, release/topology consistency and the supplied
full-ledger cursor; it returns bounded metadata bound to the request nonce.
The caller rejects absent/malformed/wrong-nonce/wrong-cursor replies.

Example, **only on a dedicated synthetic test directory**:

```sh
python3 scripts/portal_restore_offhost_probe.py \
  --synthetic-ledger-directory /path/to/private/synthetic-ledger \
  --expected-cursor <64-hex externally-held cursor>
```

The command reports `remote_memory_only_compute=true` and
`expected_cursor_matched=true` on successful readback. It **always**
reports `remote_persistence_verified=false`,
`independent_administrative_custody_verified=false`,
`rollback_resistant_high_water_verified=false`,
`real_restore_verified=false` and `production_recovery_approved=false`.

## First physical witness

On 2026-10-20, `x1-370` reached the known
`scott-Lenovo-ideapad-330S-15IKB` alias with strict SSH host key checking.
A freshly constructed synthetic fourth-key signed checkpoint and research
ledger was computed locally in disposable test storage; only the JSONL
record and challenge/cursor were transmitted to Lenovo. The healthy remote
probe returned exact cursor/nonce agreement; three separately transmitted
alterations (sequence change, ledger truncation, and duplicated record)
failed closed on the real remote host. Local stale expected-cursor input
also failed before SSH. The local test temp tree was deleted, and no
remote file or service changes were requested.

## Release boundary

The same fleet administrator can control both machines and the SSH path,
so a successful remote digest comparison **is not attestation**, cannot
independently preserve the latest cursor, and cannot survive a compromise
of common SSH/admin custody. A captured authenticated host response alone
does not prove the custodian operated under separate credentials. A remote
process without durable storage is *not* a custodian.

Next safe step requires a **separately administered** append-only witness
with independent verification keys, protected nonrewritable high-water
storage, atomic sequence compare-and-append, independent externally
published cursor and strict replay/rollback/revocation tests. Production
remains HOLD for verified immutable recovery images, independently
accepted real PostgreSQL/MinIO restore parity, OIDC and legacy rollback.
