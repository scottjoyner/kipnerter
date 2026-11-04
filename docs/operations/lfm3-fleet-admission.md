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
