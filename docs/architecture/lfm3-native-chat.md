# Kipnerter public home chat: LFM3-1.7B fleet

## Scope and boundaries
- Public `/` and `/chat` share the same LFM3-1.7B conversational UI and `POST /api/chat/completions` contract. Authenticated `/fleet` remains a separate **read-only** fleet console; its private portal API access checks are unchanged.
- The Next.js server, not the browser, calls private, explicitly configured fleet nodes over the Tailnet. No client-supplied URLs, model IDs, credentials, or tool definitions.
- This initial slice is **model-only** text chat. It does NOT invoke Hermes or any shell/tool, auto-load model weights, deploy services, expose SensorGraft data, or change production.
- Fail closed if no verified LFM3-1.7B instance responds. Never substitute Ornith, LFM2.5 or a catalog-only entry.
- Public chat does not persist message history in Kipnerter. A fleet inference server might log requests independently; establish fleet privacy policy before production release.

## Configure a private test instance
Set on the web server only:
```bash
KIPNERTER_LFM3_ENDPOINTS='[
  {"name":"joyner-r9700","baseUrl":"http://100.83.215.83:1234","model":"liquid/lfm3-1.7b-q4","adapter":"lmstudio","maxInflight":2},
  {"name":"deathstar-rx480","baseUrl":"http://100.78.106.121:1234","model":"liquid/lfm3-1.7b-q4","adapter":"lmstudio","maxInflight":1}
]'
# If upstream authentication is needed, provision it through the
# deployment secrets manager; never place credentials in this file.
```
Illustrative model IDs and ports above are **not evidence** that those hosts have the model loaded. Replace IDs with confirmed exact native catalog keys after deployment preflight. Check `GET /api/v1/models` for nonempty `loaded_instances` on LM Studio, and verify actual generation with a separate approved, bounded smoke test. OpenAI-compatible servers use `adapter=openai`, but only successful generation attests actual readiness.

## Production gates
- Require gateway-to-node Tailnet access, narrow ACLs, ingress authentication and server-side endpoint allowlist.
- Configure trusted-proxy canonical client IP, edge rate limits/abuse prevention, per-node admission and total quotas. The in-process limit is only defense in depth and is **not a distributed scheduler**.
- Never leak raw upstream errors, URLs, fleet tokens, IPs, or prompt bodies into public logs or responses.
- Add distributed capacity leases and signed execution receipts before claiming fleet-wide utilization or coordinated fairness.
- Add bounded streaming with cancellation, end-to-end CI build, deployment preview, and physical iOS acceptance.

## Agent harness evolution
LFM3 remains default for dialogue. A separate authenticated opt-in agent path may accept a `task` and return a tool proposal. Validate the proposal server-side against a narrow registry; gate side effects by explicit approval, authorization, idempotency and signed evidence. Hermes and SensorGraft/Trace DB must be reached only through scoped, audited adapters. Never execute raw model-produced commands or expose private agent capabilities on the anonymous home chat.

## Dedicated R9700 runtime and endpoint credentials

A read-only inventory observed an existing R9700 Vulkan LFM3-1.7B
research server on *loopback* port 19175 under the model alias
`lfm3-1.7b-research`, with a local API-key file. It is not yet a
Tailnet-reachable public gateway. Do **not** replace its listener, expose
the API key, or assume it is admitted for public traffic.

When a dedicated Tailnet proxy with authenticated access is approved,
set an explicit `adapter: "openai"` endpoint in
`KIPNERTER_LFM3_ENDPOINTS`; give each endpoint a `credentialEnv` name
such as `KIPNERTER_LFM3_TOKEN_JOYNER`. Supply that variable through
the deployment secrets manager only. Tokens are resolved server-side and
sent only to their corresponding endpoint, not to the browser or phone.
This does not authorize exposing the loopback port directly.

The RX 480 research artifacts and the OptiPlex GGUF file are candidate
inputs, **not** verified always-on public endpoints. Admit them only
after backend/version checks, tested GPU or CPU performance and
independent ingress identity. The router's process-local reservations
do not replace distributed capacity controls.

## Bounded parallel research (library only)
The module apps/web/lib/lfm3-parallel.mjs supports 2–3 **independent** model-only workers on separate admitted LFM3 nodes and a final LFM3 synthesis. It returns no partial synthesis when a worker fails. It requires a trusted authorized caller and is deliberately **not** wired into the public chat route; no Hermes, tools, or private database reads are authorized by these model outputs. Future integration needs authenticated identity, task-cost budgets, per-node lease coordination, and signed SG/Trace DB receipts.

## Private model-only parallel research (opt-in)

The authenticated private workspace now contains an explicit **Parallel LFM3
research** panel. Its server route is `POST /api/chat/research`, which requires
a configured NextAuth Tailscale identity, an admitted operator session, and a
same-origin browser request. Users supply only a short question. The service
assigns two independent analysis perspectives, routes their LFM3 requests to
available admitted fleet models, then synthesizes their responses on LFM3.

This is **not** the Hermes agent harness. No shell, tools, database reads,
private trace retrieval, or arbitrary client-selected endpoints are authorized.
Anonymous `/api/chat/completions` and the iOS default never invoke this
parallel endpoint. The private service restricts two concurrent requests per
app process and three attempts per authorized identity per minute; these are
defense-in-depth limits, not distributed leases or reverse-proxy abuse controls.

## November 4 staging and release boundaries

- Authenticated direct-generation checks passed on Deathstar RX 480
  (`lfm3-1.7b-rx480`, short completion in 779ms) and OptiPlex
  (`lfm3-1.7b-optiplex`, short completion in 6.91 seconds). The R9700
  Tailnet bridge is present and enforces bearer authentication, but a
  final nonempty authenticated generation acceptance is still outstanding.
- The public web completion API uses a 48KB **streaming** request-body cap,
  recent contiguous history bounded to 5,000 UTF-8 bytes to protect
  the smallest model context, GPU-first interactive routing, optional
  CPU overflow and bounded same-family failover.
- A standalone, ephemeral Next.js production-server smoke with a local
  **mock** LFM3 backend produced HTTP 200 and the expected JSON
  `reply`/`model` shape. The private parallel route rejected a
  cross-origin request with HTTP 403. This is synthetic protocol evidence,
  not real authenticated multi-node gateway admission.
- Production site topology is Caddy -> `kipnerter-web-public-v01:3000`
  (host loopback port 3337). The production host can reach all three
  authenticated Tailnet model endpoints. However, the **live public**
  `POST /api/chat/completions` still returns 404, because this draft
  has not been promoted to that public container.
- Production deployment needs securely provisioned **per-node bearer
  secrets** on the server, operator-reviewed Caddy client-IP and
  rate-limit protections, tested real responses through the staged
  gateway, exact-head CI, and an explicit cutover/rollback decision.
  The iOS branch's complete CI/simulator gates pass, but shipping its
  LFM3 default to users before this web cutover would create a broken
  chat default. No signed IPA/TestFlight upload or prod image cutover
  is claimed.
