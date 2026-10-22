# Historical web/API: source-derived executable rollback research (Oct 21, 2026)

**Release classification: research-only, not an original-production-image rollback, NOT authorized to deploy.**

This work narrows [P0 issue #50](https://github.com/scottjoyner/kipnerter/issues/50).
The private on-host archive SHA-256 and its 15-file manifest have already been
verified independently against historical Git `05955fef99cb83bfb2b4d4fb75664266e1ba385c`.
Neither original historical OCI image is present in the live production cache.
A separate DigitalOcean Oct 18 snapshot `250354430` remains retained and
unexamined pending a protected quarantine restore.

## Physical derived artifacts (x1-370, NOT production)

| Build from Git `05955fe` | Pinned local Docker image ID | Isolated result |
| --- | --- | --- |
| Historical source/API, original Dockerfile, mutable Python transitive pip resolution | `sha256:fa35913ecb97e376ae1de29ae1d100d8e830559b43364d3e97342d8fd43e0d9c` | HTTP 200 for /health, /ready, /api/v1, /api/v1/services and /api/v1/models. HTTP 404 for current-portal /api/v1/release and control-plane routes. |
| Historical source/web, original Dockerfile and original Next 15.5.21; no npm lockfile | `sha256:ff072bff623892b71492b1388eb212e66f6a1e8ae1d5f1d1c6983171882f781f` | HTTP 200 for / with historical home text; /chat 404. **Security HOLD**, npm found 3 affected production dependency packages (one critical, two high). |
| **Patched derived web only**: historical page/source files, Next 15.5.28, PostCSS 8.5.31 override, Sharp 0.35.5, full locked npm tree | `sha256:3d6cc7837f1d5a8032b0eae71876d3784d50162691789dfb8d22a9d0f57958b2` | npm ci and npm audit --omit=dev --audit-level=high both PASS, **0 known advisories for the installed locked dependency tree at test time**; Next production build PASS; isolated / 200 with historical home content, /chat 404. |

**Critical provenance distinction:** these are all **newly built derived images**.
The original OCI config, byte-identical layers, historical build dependency
resolutions, and authenticated original web/API operational equivalence are
NOT proven. Neither derived web is a drop-in backend for the **new** portal.
The old API lacks its control-plane/release routes and the old web intentionally
returns 404 for /chat. A complete two-service fallback can only be considered
for **historical route behavior** pending independent owner approval.

## Pinned hardened-web recipe, WITHOUT modifying historical source

Stored in `recovery/legacy-derived-web/`:
- `Dockerfile`: SHA-256
  `2cd3c24c72d7fed2bf93306879cdf2506db0ce1bfeb6934cc9380ec4f05bf589`
- `package.json`: SHA-256
  `5ba63c7ac1564ab8014061bba9f34156cd47984c4d8a8c03ce9df02a9b5a574b`
- `package-lock.json`: SHA-256
  `b430338b28fe62a8ed9209b45891838e7d236cd93f4d6a8297f7c8335493b81a`

The recipe uses all three Docker stages from the immutable
`node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402`,
`npm ci --ignore-scripts`, and a build-time **blocking** npm security audit.
The complete npm v3 lockfile fixes package identities and integrity hashes.
The build audit must be **rechecked** against the current advisory feed
before any independent production review. A high/critical advisory causes
the build to fail. The forced PostCSS override is a compatibility
change: its build/homepage tests passed, but this does NOT establish
full browser/identity/webhook behavior or authorization safety.

To reproduce on an isolated, operator-approved **research** worker:
```bash
set -euo pipefail
GIT_REV=05955fef99cb83bfb2b4d4fb75664266e1ba385c
SCRATCH="$(mktemp -d -t kp-derived-XXXXXX)"
chmod 0700 "$SCRATCH"
# Execute against an authenticated local checkout containing the pinned revision.
git archive "$GIT_REV" apps/web | tar -xf - -C "$SCRATCH"
cp recovery/legacy-derived-web/{Dockerfile,package.json,package-lock.json} "$SCRATCH/apps/web/"
DOCKER_BUILDKIT=1 docker build --pull=false \
  -t kipnerter-legacy-derived-web:hardened-review-only "$SCRATCH/apps/web"
# This recipe does not push, start public services, change production or
# grant recovery/cutover approval. Remove only the created scratch folder.
```

The API research image used the unchanged original `apps/api/Dockerfile`
(from `05955fe`) and locally cached `python:3.12-slim`. This image
has **no frozen full transitive pip lock** or package-security admission.
It must be reviewed and dependency-locked independently.

## Physical source-derived two-service restart rehearsal

`scripts/portal_legacy_derived_pair_rehearsal.py` is research-only.
It requires exact cached immutable image IDs, creates uniquely generated
Docker containers for both roles, and reads back:
`--network none`, **no published host ports**, **no mounts or Docker
volumes**, read-only root filesystems, non-root users, dropped Linux
capabilities, no-new-privileges, bounded pids/CPU/memory and bounded tmpfs.
It verifies old routes **inside each container**, sends SIGKILL only
to those exact recorded disposable IDs, checks they disappear, then starts
and qualifies a fresh pair. A separate finally block removes any
owned leftovers, with safe-to-cutover **always false**.

Physical experiments on x1-370:
- Original source-derived API + source-derived **unpatched historical web**:
  **PASS** for two independent launch/route/kill/relaunch cycles.
- Original source-derived API + **hardened derived web**:
  **PASS** for two independent launch/route/kill/relaunch cycles.
- Docker readback confirms **zero leftovers** after experiments.
- Historical `/` = 200 and original homepage; `/chat` = 404 (expected).
  API `/health`, `/ready`, `/api/v1` = 200; new portal-specific
  release/control-plane routes = 404 (expected).
- Source-derived mechanics PASS does not test a production rollback,
  an upgrade to a different approved image or replacement of live ingress.

To repeat *only* with the exact research image IDs above:
```bash
python3 scripts/portal_legacy_derived_pair_rehearsal.py --research-only
python3 scripts/portal_legacy_derived_pair_rehearsal.py --research-only \
  --web-image-id sha256:3d6cc7837f1d5a8032b0eae71876d3784d50162691789dfb8d22a9d0f57958b2
```

Unit tests are offline: `scripts/tests/test_portal_legacy_derived_pair_rehearsal.py`
and `scripts/tests/test_portal_legacy_derived_web_recipe.py`. They
reject mutable/incorrect IDs, arbitrary container names, privileged or
mounted configs, exposed ports, duplicate/missing dependency integrities,
and any status attempting to promote derived artifacts to original OCI.

## Remaining mandatory gates

1. **Original production OCI recovery:** run owner-gated quarantine
   firewall inventory, separately authorize a restored server and safe
   first-packet network isolation, inspect retained Oct 18 DO snapshot
   privately for immutable original web/API configs and layers.
2. **If derived replacements are approved:** independent review of exact
   old route/auth/backend parity and a *genuine* failed-upgrade rollback
   to both matching service versions; API transitive lock, security
   audit, supply-chain attestation, and artifact custody. The patched web
   changes installed dependencies from the original application.
3. **Data recovery custody:** real PostgreSQL 50-table/17,422-row
   scratch parity and MinIO 2-object exact SHA-256 body parity PASS,
   but write-fenced point-in-time consistency, anti-rollback high water,
   independent off-host custody remain outstanding.
4. Production browser OIDC acceptance, explicit operator release
   authorization, and safe upgrade/cutover. Public `/chat` remains
   HTTP 404. **Do not merge/deploy draft portal PR #18 because
   this research harness succeeds.**

All research images remain local to x1-370. No image was uploaded to a
registry, no production host accessed or modified for these builds, and
no production service was restarted.
