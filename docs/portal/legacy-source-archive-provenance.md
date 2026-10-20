# Legacy source archive provenance — exact file-level integrity, NOT an OCI rollback

The original legacy web/API image IDs could not be found on accessible
Docker daemons (issue #50). A separately approved private source-retention
run [39351786011](https://github.com/scottjoyner/kipnerter/actions/runs/39351786011)
preserved selected build inputs in a 0600 owner-private
`legacy-app-source-before-17-20261019.tar.gz` archive with a schema-1
receipt. The source snapshot excludes `.env`, dependency caches, logs,
database dumps, keys and other disallowed extensions by design. It is
**not** authoritative Git revision custody or a recovered image.

## Read-only private verifier

`scripts/portal_legacy_source_archive_verify.py` can independently
recompute the receipt's compressed gzip-tar SHA-256 and source manifest
hash: for each sorted source member, SHA-256 of
`relative_path_utf8 || NUL || SHA256(file_bytes)`. It uses read-only,
no-follow file descriptors scoped to a 0700 owner-private directory.
It rejects symlinks/hardlinks/special files, permissive source/receipt
modes, oversized records, duplicate JSON fields, directory traversal,
missing required Compose and web/API build inputs, unexpected tree paths,
source length/count differences, and inconsistent `package-lock.json`
presence. Source file contents never appear in output.

The input is bounded to a 128-MiB compressed archive, 128 MiB aggregate
uncompressed source, 8,000 entries and 16 MiB per regular member.
No extraction, Docker import/build/pull, live production access,
private key parsing or archive copying is performed.

**Only a separately authorized private operator** can run this on its
original custody host, after completing normal Tailscale SSH identity
verification:

```bash
python3 scripts/portal_legacy_source_archive_verify.py \
  --private-custody-dir /home/kipnerter/.local/state/kipnerter-release/state-backups
```

Synthetic local regression tests:

```bash
python3 -m unittest scripts.tests.test_portal_legacy_source_archive_verify -v
```

Passing yields `SOURCE_CUSTODY_VERIFIED_NOT_RUNNABLE` with all
production permission, original OCI image recovery, executable rollback
and independently administered custody flags explicitly false.
This is **a byte-integrity and structural contract, not proof the
archive is genuine**, because the same administrator could replace both
archive and receipt; an independent append-only signed witness remains
absent. It also does not establish whether the preserved original image
was built from those exact source bytes.

The verifier must not be configured to publish source tarballs, raw file
names, hashes, private launch environment values or filesystem contents
in GitHub Actions artifacts, logs or PR discussions.

## Hosted CI parity for PR #18

The `ci` workflow previously triggered on `master`, `main`,
`agent/**` and PR events, but exact recovery feature branch pushes
had **zero hosted workflow runs/checks**. Its read-only test workflow
now explicitly permits push builds of the exact existing branch
`feat/unified-fleet-portal-20261017`; this branch-scoped CI runs the
existing API, web, stateless build/configuration, Terraform, secrets,
and new recovery unit tests. It grants only `contents: read` and
does not use protected production environment credentials or Tailscale
access.

An actual successful hosted run on the exact published commit must be
checked separately. No CI configuration change is an approval to
publish the public chat route.

## Executable rollback remains separate

An old OCI-compatible rollback requires independently retained image
configuration, layers, entrypoint/user/env provenance or a reviewed
**derived** build; private secret review; exact source/runtime
compatibility; two isolated host-port-free test launches with old
health, auth and route parity; and repeatable rollback after induced
failure. Real PostgreSQL and MinIO backup restoration and independently
managed high-water checkpoints remain additional NO-GO gates.
No production service, data, image or traffic was changed.
