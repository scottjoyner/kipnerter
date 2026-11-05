# Fast, genuine LFM3 staging on x1-370 — private only

Last proven: **2026-11-05**, Fleet Commander direct execution on **x1-370**. This is an additional **temporary local-only staging backend**, not a public deployment, RX480 credential exception, or a modification of the existing production stage.

## What is running

| Component | Bound address | Identity | Resource limits |
|---|---|---|---|
| Official LFM3-1.7B Q4_K_M GGUF through llama-server | 127.0.0.1:19181 | lfm3-1.7b-x1-fast | 6 CPUs max; 2500 MiB RAM; zero swap; 80 tasks |
| Exact PR #96 Next.js app | 127.0.0.1:3357 | source c2a1dd2978ec7c7215e072bb62080ec2178e5a5b | 0.75 CPU max; 384 MiB RAM; zero swap; 110 tasks |

Official model: /home/scott/models/LFM3-1.7B-Q4_K_M.gguf; 1,099,627,808 bytes; SHA-256 **3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4**.

Reviewed source: /home/scott/git/kipnerter-lfm3-fast-stage-20261105, exact PR #96 commit, with successful locked dependency installation and production Next.js build.

Running transient user-systemd units:
- kipnerter-lfm3-fast-model-20261105.service
- kipnerter-lfm3-fast-web-20261105.service

Original x1 research LFM3 localhost port 19180 remains untouched. The existing production-host CPU LFM3 frontend on localhost port 3356 remains untouched. Neither RX480 credentials nor Caddy/public routing changed.

**Actual Next.js end-to-end inference:** three separate HTTP 200 real LFM3 requests completed in **2671 ms**, **2273 ms**, **2409 ms**. The separate read-only audit later passed in **1340 ms**. These are *four individual short-prompt samples*, not p50/p95, long-prompt performance, or public SLO. A previous one-CPU production stage took **36950 ms** on a short request. Memory observed model ~698 MiB, web ~44 MiB, neither using swap. The host had ~26 GiB MemAvailable but its general host swap was already full.

## Authorized operator demo

On a Tailscale-connected Mac with the x1-370 SSH host key already verified against trusted operator records, run:

    ssh -N -L 127.0.0.1:3357:127.0.0.1:3357 scott@100.64.43.123

Open http://127.0.0.1:3357/chat on that Mac. The fast model and Next.js web service both listen **only on loopback**. Do not bind either on 0.0.0.0, enable Tailscale Funnel, publish a public Caddy route, or expose the model unauthenticated to other hosts.

### The Fleet Commander SSH fix

Fleet Commander shell sessions use an isolated HOME. The earlier Tailscale SSH commands to Joyner and xwing could not find authorized host-key evidence. Both machines were subsequently authenticated using preexisting, pinned ED25519 identities in /home/scott/.ssh/fleet-known-hosts with StrictHostKeyChecking=yes and HOME=/home/scott. No TOFU, replaced host keys, or disabled verification. Joyner had ~0.8 GiB spare system RAM; xwing ~3.7 GiB; x1 had sufficient headroom for bounded local staging.

## Repeatable no-write audit

From the feature PR's audit script on x1-370:

    python3 scripts/lfm3_x1_fast_stage_audit.py

This independently checks machine/principal, exact source commit, full model SHA-256, active user-systemd unit identities, hard memory/CPU/task and no-swap limits, exclusively loopback listeners, host spare RAM, one actual browser page, and **one genuine Next.js-to-LFM3 generation**. It logs only pass/hold evidence and timing, not prompt/reply text or credentials. The 15-second single-sample guard is a canary, not a p95 objective.

The GitHub Actions contract workflow tests source and policy syntax only, with **no fleet credentials or production access**. Passing hosted CI is not a live staging assertion.

## Recovery and durability gates

The current units are **transient, nonpersistent across reboot**. The presently used llama-server executable lives under /tmp/lfm3-test-rt and may be absent after reboot. Do not assume automatic restart or durable high availability.

Before any operator-authorized restaging:
1. Verify identity x1-370/scott, at least 8 GiB MemAvailable, host workload stability, and absence of both reserved ports and stage units. Do not evict existing models or clear swap to force a pass.
2. Reverify the official GGUF digest and source exact commit. Review and pin the current llama-server binary and dependencies independently. Never download or substitute an unreviewed executable.
3. Build the Next.js app from the pinned lockfile. Establish only the reviewed limits: model maximum 6 CPUs/2500 MiB/no swap; web maximum 0.75 CPU/384 MiB/no swap; no extra network exposure.
4. Configure the web server's sole OpenAI-compatible model endpoint with the exact fields: name=x1_fast_cpu, baseUrl=http://127.0.0.1:19181, model=lfm3-1.7b-x1-fast, adapter=openai, role=interactive, maxInflight=1, maxOutputTokens=128.
5. Re-run real HTTP acceptance. If stage setup fails, stop **only newly created stage units**; leave existing research LFM3, original production CPU staging, keys and Caddy untouched.
6. Obtain separate security review and authorization before persisting units across reboot, allowing any inter-node route, or changing public HTTPS/iOS traffic. Preserve a verified rollback.

**Release decision:** fast private LFM3 product demo PASS. Public cutover, protected RX480 credential, durability, concurrency, long-context quality, and physical iOS/TestFlight remain HOLD.
