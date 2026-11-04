# Kipnerter public home chat: LFM3-1.7B fleet

## Scope and boundaries
- Public `/` is a conversational UI. Authenticated `/chat` remains a separate **read-only** fleet console.
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
