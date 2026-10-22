# Synthetic custodian compare-and-append ledger (LOCAL RESEARCH ONLY)

This is a **non-production, single-host prototype** for the next checkpoint
high-water recovery gate. It adds serialized, hash-linked local persistence
on top of `portal_restore_high_water.py`. It is NOT an externally administered,
immutable, append-only service. A filesystem `fsync()` provides a local crash
durability attempt, not independently retained high-water evidence.

## Contracts

`scripts/portal_restore_custodian_ledger.py` exposes Python calls:

- `append_verified_tip(directory, chain=..., anchor=..., roles=...,
  observer=..., signed_tip=..., custodian_trust=...,
  expected_cursor=<externally retained hex digest>,
  bootstrap_expected=(sequence, checkpoint_digest))`
- `inspect_local_log(directory, expected_cursor=<externally retained digest>)`

The six existing verifier inputs are the same as the high-water signature CLI.
No private signing keys, production data, or credentials are persisted. The
caller must create a **dedicated, owner-private (0700) research directory**
first. The file is created with mode 0600; symlinks, FIFOs, hardlinks, other
owner identities and permissive files fail closed. The tool opens the final
directory and log with no-follow, locks the same open descriptor, bounds input
to 1 MiB and 1024 records, uses canonical JSON lines, and checks the
per-record hash chain before appending. A caller must retain the prior
record-cursor digest outside the log and supply it for each read/write.
Concurrent stale writes, repeated checkpoint sequences, skipped sequences,
changed release/topology and forks fail closed. A successful append fsyncs
the descriptor; first creation fsyncs its directory entry.

Bootstrap is *not automatic*: a separately chosen expected sequence and
checkpoint digest must match the fully verified fourth-key signed tip.
This requirement avoids silently treating an untrusted candidate as
authoritative. **However**, since the bootstrap pin is passed by the caller,
its independent origin cannot be verified by this module.

## Explicitly unproven

A machine administrator can rewrite/delete the whole log and present a
rolled-back external cursor and bootstrap pin. A compromised custodian key
can sign a forged tip. The prototype does not prevent host rollback, key
compromise, physical seizure, network partition or a malicious privileged
operator. It has **no HTTP interface, deployment workflow, production
connection, raw trace collection or approval-setting path**.

Every response reports
`independent_custody_verified=false`,
`rollback_resistant_persistence_verified=false`, and
`production_recovery_approved=false`.

## Required for actual production high-water admission

Provision a separately administered and independently monitored custodian
with immutable or non-rewritable storage, protected signing-key custody,
strict authentication, append-only compare-and-swap, and verifiable
external distribution of the latest signed digest to a second authority.
Demonstrate the witness rejects a rolled-back entire database, replayed
cursor, revoked signer, fork and stale identities, including after a service
restart. Then perform real restore parity checks in a distinct staging
environment against approved source images and encrypted backup artifacts.
Only independently accepted evidence can inform a production release gate.

The local test suite exercises two valid successive signed checkpoints,
simultaneous competing writes, stale optimistic cursors, missing bootstrap
pin, forged signatures, deleted/truncated/corrupted records, unsafe paths
and incorrectly permissioned files. It neither performs actual Postgres/
MinIO restoration nor connects to a fleet host.
