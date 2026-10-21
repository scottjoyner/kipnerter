# Historical web/API source provenance — October 20, 2026

**Evidence status:** original source snapshot matched; original production OCI images
**NOT recovered**. Issue [#50](https://github.com/scottjoyner/kipnerter/issues/50)
remains P0/HOLD.

## Immutable Git source identified

A read-only production workflow
[run 39351786011](https://github.com/scottjoyner/kipnerter/actions/runs/39351786011)
privately archived the former web/API build context, without preserving
secrets, database content, or Docker image configuration. Its publicly
logged schema-1 receipt contains:

| Evidence | Value |
| --- | --- |
| Historical Git source tree | `05955fef99cb83bfb2b4d4fb75664266e1ba385c` |
| Source manifest SHA-256 | `68475f07e32adcc783bba4ec02faf44709bff90ae8e77024b7206d2871d3a07b` |
| Archived source file count | **15** |
| Private gzip tar SHA-256 (receipt only) | `dd69c263f2c82f99bbd9d259726c7a1edd35e8f9e0a58925e23bf3b9d78d21d9` |
| Web dependency lockfile archived | **No** |
| API Dockerfile SHA-256 | `691fa56601ad18c98e96595aee2d738c5b52fe6445e75dee6269843a3bf106f4` |
| Web Dockerfile SHA-256 | `f7df4a0f05209509328e6319c2c4375a22f35b1e64bcbcec950b1ecd41f6c7fa` |

**Independent, no-network Git-tree recomputation on x1-370 succeeded.**
The original one-shot source preservation logic,
`scripts/portal_legacy_source_preserve_once.py` at commit `f490955`,
selects the two root Compose inputs, plus allowlisted files in
`apps/api`, `apps/web` and `infra/caddy`; it excludes credentials,
cache/build folders, `.env*`, database, logs and secret-bearing file
extensions. It hashes sorted entries as
`SHA256(relative_path_utf8 || NUL || SHA256(file_bytes))`, concatenated
within a second SHA-256 stream.

Applying the *same file selection and hash function* to the pinned Git
tree `05955fef99cb83bfb2b4d4fb75664266e1ba385c` produced the
**exact** logged source manifest hash, for **exactly 15 files**. Both
Dockerfile raw SHA-256 digests also matched the production read-only
classification from
[run 39340561641](https://github.com/scottjoyner/kipnerter/actions/runs/39340561641).
Of 29 eligible unique historical app-source trees evaluated locally,
this was the only manifest match.

The old source contained API requirements
`fastapi==0.116.1`, `uvicorn[standard]==0.35.0`,
`pydantic-settings==2.10.1`, and `httpx==0.28.1`.
Its web `package.json` pins Next 15.5.21, React 19.1.9 and
React-DOM 19.1.9 as **top-level** dependencies, but has no archived
transitive dependency lockfile. The original web Dockerfile uses
`npm install`, not `npm ci`.

## What this proves—and what it does not

The selected source **bytes** have a reproducible Git identity, and they
match the **same-administrator archive receipt's** source manifest.
This is more than a Dockerfile-only match. **It is not independent custody
of the receipt or proof the old *running* containers were built from this
source.** The prior image configs, entrypoints, binary layers and
dependency resolutions remain unproven.

The original live web and gateway image IDs are absent from the
production Docker image cache, and the references were classified as
local/default-tag, **not immutable registry digests**, by
[production workflow 39340561641](https://github.com/scottjoyner/kipnerter/actions/runs/39340561641).
A restored source tree, `docker export` rootfs tar, or rebuild cannot be
called the **original OCI image**. The archived gzip tar itself was not
downloaded or rechecked during the Git-tree comparison; the privately
scoped on-host archive verifier must still be run after authorized
operator Tailscale identity verification.

On x1-370, `python:3.12-slim` was cached but the old
`node:22-alpine` web build base was **not**; root disk use was about
95%. No image pulls, npm installs, builds, Docker imports or source
exports were authorized or attempted for this lineage finding.

## Smallest safe path to a runnable rollback candidate

1. **Operator-owned production access:** complete required Tailscale
   reauthentication; run the existing private source verifier against
   the already preserved archive and receipt (no public upload), then
   independently retain a signed/off-host receipt and authorize source
   transfer if appropriate.
2. **Reconstruction inputs:** pin the immutable Git tree above and
   *digest-pin* approved Linux/amd64 base images. Resolve, freeze,
   scrutinize and independently archive the missing web transitive
   dependencies; do not perform uncontrolled `npm install` and assume
   equivalence. Preserve reproducible build recipe hashes and receipts.
3. **Owner-approved isolated derived builds only:** use a worker with
   approved capacity and deny production mounts/ports/credentials.
   Mark any image `DERIVED_NOT_PRIOR_PRODUCTION_IMAGE`; inspect config
   for secret exposure. Verify complete OCI manifests and layer diffIDs
   using the existing streaming verifier.
4. **Physical rollback admission:** boot **both** derived web and API
   separately, confirm historical route/auth parity and web page behavior,
   simulate a failed upgrade and prove a safe reversal. The prior research
   API images missing control-plane/release routes are **not** admitted
   as compatible alternatives.
5. Independently prove genuine PostgreSQL and MinIO restoration,
   custody and high-water freshness, production OIDC and authorized owner
   acceptance. **Do not change live containers, public `/chat`
   ingress or persistent data until all gates pass.**

**All source lineage, authentic image recovery, rollout and cutover
status flags must remain distinct. Production cutover: HOLD.**
