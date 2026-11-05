# Independent CPU LFM3-1.7B staging candidate — production stays HOLD

This opt-in design is separate from the RX480 protected worker and does **not**
authorize an RX480 key, public Caddy changes, TestFlight release, or live site
cutover. It is intended only if the *existing production host* has enough
unused CPU, RAM, and disk to avoid harming its current workloads.

## Read-only feasibility first

Run **only** as the existing `kipnerter` principal on the approved host, from
an owner-reviewed checkout:

```bash
bash scripts/lfm3_cpu_stage_preflight.sh
```

The preflight requires x86_64, Docker/Compose, at least two schedulable CPUs,
6 GiB of currently available RAM, 10 GiB of disk headroom, no existing CPU
stage container names and an unoccupied 127.0.0.1:3363. It reports
`CPU_STAGE_READINESS_PASS` or `CPU_STAGE_HOLD`. It does not read secrets,
download software, start containers, or touch the RX480 runtime. The resource
threshold is a safety *floor*, not a guarantee of acceptable token latency.

If capacity is insufficient, **do not lower thresholds to force a pass**.
Use a fleet node with demonstrably idle RAM/CPU as an isolated alternate
model host; retain a separate model-only network path and do not expose it to
the public internet. Do not claim this production-host stage is deployed.

## Required reviewed artifacts before manual activation

- An exact-source Next.js web image with a verified immutable digest.
- A separately reviewed LFM3-capable llama.cpp CPU server image, entrypoint
  `/app/llama-server`, also referenced by an immutable image SHA-256 digest.
- The official Liquid AI `LFM3-1.7B-Q4_K_M.gguf` regular file (1,099,627,808 bytes),
  SHA-256 `3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4`,
  readable by the staging container's unprivileged uid 10001. Review the
  model's `lfm1.0` license before provisioning.

The model file's hash and size originate from Liquid AI's official Hugging
Face Git LFS pointer at commit `b3f2ae5d73cd3c91bf40e8ba752c648aa05dffdf`.
The CPU server image's actual entrypoint and flags must be tested with the
pinned artifact before using it on production. A generic unpinned `:latest`
Docker tag is not approved.

The operator must place the verified model and both reviewed images on the host
through an approved artifact path. No production credentials are involved.
Do not automatically pull images, model weights, or copy any fleet tokens from
inside the activation script.

## Explicit manual activation (only after readiness and approval)

```bash
export KIPNERTER_LFM3_CPU_WEB_IMAGE='approved-web/image@sha256:<64-char-digest>'
export KIPNERTER_LFM3_CPU_MODEL_IMAGE='approved-runtime/image@sha256:<64-char-digest>'
export KIPNERTER_LFM3_CPU_MODEL_FILE='/approved/path/LFM3-1.7B-Q4_K_M.gguf'
export KIPNERTER_LFM3_CPU_STAGE_APPROVED=YES
bash scripts/lfm3_cpu_stage_activate.sh
```

These are placeholders, **not commands to run unedited**. Activation checks
immutable image references and local presence, verifies the GGUF checksum,
reruns the read-only resource gate, and parses the Compose manifest before
starting anything. It uses an internal-only model network, a separate preview
network, CPU-only llama.cpp with one in-flight request, capped RAM, CPU and
pids, no RX480 key mount, and host loopback port 3363 **only** for Next.js.

A `CPU_STAGE_REAL_PASS` requires a genuine arithmetic completion from the
official model *through the actual Next.js API*. If acceptance fails, the
script removes only the named containers it created with the matching Compose
project; it must not stop preexisting fleet or production services.

## Release boundary

Even a real, passing CPU stage establishes **localhost staging only**.
Public `kipnerter.com`, edge rate limiting, privacy/retention,
signed native iOS distribution and production rollback gates remain separate
HOLD conditions. The original RX480 credential gate is unchanged.
