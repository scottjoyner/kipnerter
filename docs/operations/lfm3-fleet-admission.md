# LFM3-1.7B fleet admission and rollback (research / staging)

Checked November 4, 2026. This is a private-Tailnet service inventory, **not**
evidence of a public kipnerter.com deployment or TestFlight release.

## Observed service inventory

| Node | Runtime | Tailnet service | Model alias | Admission |
| --- | --- | --- | --- | --- |
| Joyner / R9700 | Vulkan1 research instance, proxied by rootless `socat` | `100.83.215.83:19176` | `lfm3-1.7b-research` | HEALTH / AUTH PASS; complete authenticated answer still to verify |
| Deathstar / RX 480 | Dedicated Vulkan0 llama.cpp, QAD-Q4_0 | `100.78.106.121:19176` | `lfm3-1.7b-rx480` | HEALTH / AUTH PASS; localhost canary returned a correct nonempty answer |
| OptiPlex | Dedicated CPU-only AVX2 llama.cpp, Q4_K_M | `100.69.158.114:19176` | `lfm3-1.7b-optiplex` | HEALTH / AUTH PASS; localhost canary returned a correct nonempty answer |
| Lenovo | LFM3 Q4_K_M GGUF and rebuilt CPU llama.cpp server | none | none | HOLD: slow system-disk I/O prevented timely model startup; canary stopped |
| x1-370 | Existing locally loaded workhorse models | unchanged | n/a | Preserve local work; do not require node for public chat |

Lenovo's legacy LM Studio server rejected the LFM3 architecture. A compatible\nCPU research server was rebuilt without installing system packages, but model\nstartup was observed in kernel block-I/O wait: only ~108 MB had been read after\n39 seconds. Its local canary was terminated cleanly, existing listeners were\nunchanged, and **no Lenovo service was admitted**. Address disk throughput or\nmodel staging on faster media before retrying. Beelink, Destroyer and xwing\nalso contain LFM3 artifacts, but were not admitted because of current workload\nand RAM constraints.\n\nAll three newly installed listeners are **Tailnet-bound** rather than publicly
internet-bound. Model listing without a bearer token returned HTTP 401 on each.
These checks confirm that an ingress exists and rejects missing credentials;
they do **not** prove end-to-end generation through the public gateway. The
R9700 bridge forwards to an **already-running, API-key protected localhost**
server; it does not start or evict any model.

RX 480 canary: 1.595 seconds to an actual short completion, with a 64-token
October 28 research benchmark of ~108.18 tokens/s for QAD-Q4_0 (historical
measurement, not production p95). Post-start RX 480 VRAM free was ~2.33 GB.
OptiPlex CPU canary: 4.56 seconds to a short valid completion. Longer prompts,
concurrency, thermal behavior and error rates have not yet been qualified.

## Gateway roster

For a **private staging** web deployment that has reviewed Tailscale reachability
and ACLs, set the server-only `KIPNERTER_LFM3_ENDPOINTS` JSON array to:

```json
[
  {
    "name": "r9700",
    "baseUrl": "http://100.83.215.83:19176",
    "model": "lfm3-1.7b-research",
    "adapter": "openai",
    "maxInflight": 1,
    "role": "interactive",
    "credentialEnv": "KIPNERTER_LFM3_TOKEN_R9700"
  },
  {
    "name": "rx480",
    "baseUrl": "http://100.78.106.121:19176",
    "model": "lfm3-1.7b-rx480",
    "adapter": "openai",
    "maxInflight": 1,
    "role": "interactive",
    "credentialEnv": "KIPNERTER_LFM3_TOKEN_RX480"
  },
  {
    "name": "optiplex",
    "baseUrl": "http://100.69.158.114:19176",
    "model": "lfm3-1.7b-optiplex",
    "adapter": "openai",
    "maxInflight": 1,
    "role": "overflow",
    "credentialEnv": "KIPNERTER_LFM3_TOKEN_OPTIPLEX"
  }
]
```

The dedicated per-node API keys live in private files on their respective
hosts; the existing Joyner research service maintains its original key. Securely
distribute credential **values** using the web deployment's secret manager.
Never copy keys into source control, iOS configuration, web responses, build
artifacts, or shell logs. A missing credential fails closed. The public iOS app
only accesses `https://kipnerter.com/api/chat/completions`.

The router checks the explicitly admitted endpoints' model catalogs and
requires a nonempty completion before treating a request as successful. It
prefers healthy interactive GPUs and uses the CPU overflow pool when they are
unavailable or fully reserved. Independent tasks may use the model-only
parallel research library, but anonymous chat does not get tool or agent
permissions. In-flight counts are **process-local**, not globally leased.

## Safe operator checks

On a node, use `systemctl --user status` and
`journalctl --user -u <unit> -n 50` (redact any credentials).
The installed units are:

- Joyner: `kipnerter-lfm3-r9700-bridge.service`
- Deathstar: `kipnerter-lfm3-rx480.service`
- OptiPlex: `kipnerter-lfm3-optiplex.service`

From an authorized Tailnet node, `GET /health` should return 200, and
unauthenticated `GET /v1/models` should return 401. A properly authenticated
**bounded generation** on each exact alias is still required for final
admission. Verify model hash/provenance, expected GPU offload, reserved
capacity, per-node p50/p95 and signed SensorGraft/Trace DB receipts before
claiming a production-ready distributed fleet.

## Reversal without touching any other model

For a newly installed service, run on its own node:

```sh
systemctl --user disable --now kipnerter-lfm3-rx480.service
```

Substitute the appropriate unit name for R9700 or OptiPlex. The R9700 command
stops **only the Tailnet bridge**; its preexisting localhost research process
remains untouched. The RX 480 and OptiPlex commands stop **only their dedicated
new server**. Do not kill generic `llama-server` processes, change existing
model-load state, or alter x1-370. Before production rollout, require trusted
reverse-proxy canonical-IP abuse controls, credential provisioning, a staged
public gateway smoke test, iOS device acceptance, and an authorized release
decision. Production / TestFlight remains HOLD.

## November 4: isolated production-host staging, no public cutover

Built the exact hosted-CI-passing web SHA
`5370ec124b182a028a1baa93acb72761f2d4b6eb` from an immutable
`git archive` on x1-370 into
`/opt/kipnerter-lfm3-stage-20261104` on `kipnerter-prod-01`.
Its 232 MB image is `kipnerter-lfm3-staging:5370ec1`.

The **separate** staging container `kipnerter-lfm3-stage-5370ec1`
runs on Docker's `kipnerter_frontend` network, limited to 0.75 CPUs,
512 MiB RAM and 150 processes. It is bound strictly to host
`127.0.0.1:3347`; it is **not** connected to a public Caddy route.

Observed staging HTTP checks:
- `GET /` -> 200 with the new chat home page.
- `POST /api/chat/completions` -> 503 (per-node credentials are deliberately
  **not** present in staging; the exact model roster has credential references).
- Unauthenticated cross-origin `POST /api/chat/research` -> 403.
- Existing production web container remains running; public
  `POST https://kipnerter.com/api/chat/completions` still -> 404.

The staging image is **not** a production cutover and is not the newest
unmerged security patch. For rollback of the localhost-only staging service,
the operator can stop/remove `kipnerter-lfm3-stage-5370ec1` via Docker
without touching `kipnerter-web-public-v01` or Caddy.

### Canonical client IP for a future public cutover

The newer web route ignores the client-spoofable `X-Real-IP` header, validates
the **last proxy-appended** `X-Forwarded-For` value as IPv4/IPv6 and
groups absent/invalid headers as `unknown`. Production Caddy must
overwrite the headers on the upstream hop. When updating the *reviewed*
public Caddy route, ensure its reverse proxy contains the equivalent of:

```caddy
reverse_proxy kipnerter-web-public-v01:3000 {
    header_up X-Forwarded-For {remote_host}
    header_up -X-Real-IP
}
```

Review CDN, trusted-proxy and actual ingress topology first. This canonical
IP check is still process-local; deploy and verify edge/global abuse limits
before opening anonymous chat to the internet. **Do not apply this snippet
to running production Caddy until all release gates pass.**

### Real two-node parallel model canary

On the private x1-370 harness, each model's bearer token was read and used
**only on its own inference node**, with no key copied to x1-370 or to the
production droplet. The actual `completeFleetChat` router returned:
- RX 480 GPU: 200, reply `4`, 1.342 seconds.
- OptiPlex CPU: 200, reply `4`, 9.251 seconds.
- Opt-in `runParallelLFM3Research`: RX 480 and OptiPlex each performed
  one independent analysis, RX 480 synthesized the result, 200 in
  19.185 seconds.

These are real, bounded model-only generations, but use an ephemeral
SSH-host-local transport for the smoke test. They **do not** establish that
the live Next.js HTTP container has production bearer credentials.

### iOS release pairing

The iOS native default remains pinned to
`https://kipnerter.com/api/chat/completions`, not node IP addresses.
Draft iOS PR #448 at `e56ed62698527a9698fc6c52f52c6a4fbb8d5dbe`
has green exact-head contract, portable, standalone-host and CI gates.
The TestFlight workflow additionally requires a **live** correct-model
HTTPS response before upload. As the public route is still 404,
TestFlight upload remains **HOLD**, even though simulator validation passes.

