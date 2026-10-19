# Reproducible fleet-chat source bundle (no deployment authority)

`scripts/portal_stateless_bundle.py` builds a deterministic gzip/tar archive
using only immutable tracked Git blob bytes from the **exact checked-out
platform SHA**, not untracked worktree files or cached dependencies. It selects
only `apps/web/`, `apps/api/`, `docker-compose.yml` and
`compose.fleet-preview.yml`. It omits spatial API source, database/object
store data, `.env` secrets, symlinks, submodules, Node caches and build outputs.

In the reviewed checkout, from the repository root:

```sh
SHA="$(git rev-parse HEAD)"
python3 scripts/portal_stateless_bundle.py build --root . --sha "$SHA" --out /tmp/kipnerter-stateless.tgz
python3 scripts/portal_stateless_bundle.py verify --archive /tmp/kipnerter-stateless.tgz --sha "$SHA"
sha256sum /tmp/kipnerter-stateless.tgz
```

The verifier refuses unexpected members, repeated names, non-regular tar
entries, external paths, changed modes, changed content, wrong revision, missing
essential source, forbidden spatial filenames, and length violations. Source
limits: 512 tracked files, 8 MiB per file and 64 MiB total. The build copies
neither source secrets nor volumes, and has no network or Docker actions.

Archive SHA-256 must be independently pinned by the operator before using it
for staging. The manifest is **not a signature** and cannot prove the release
operator's identity, a production rollback, model authorization, real OIDC, or
stateful recovery. CI builds two archives and checks byte equality.

This archive is only a preparation input. Do not untar it into the active
`/opt/kipnerter` tree, start Compose without a preflight, use a production
project name, or assume that a stateless candidate authorizes public ingress.
A reviewed, authorized staging deploy and exact revision rollback must be
completed in a separate protected workflow.
