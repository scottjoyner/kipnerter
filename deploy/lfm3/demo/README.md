# Kipnerter LFM3 offline HTTP demo acceptance

Run from an isolated trusted checkout of this branch:

```sh
cd apps/web
npm ci --no-audit --no-fund
npm run build
python3 ../../scripts/lfm3_demo_acceptance.py
```

The test launches **the actual production-built Next.js web app** on a random loopback port, plus a separate Python-stdlib OpenAI-compatible fixture on another loopback port. It uses a temporary, server-only `KIPNERTER_LFM3_ENDPOINTS` pointing to `127.0.0.1` and **no bearer credentials**. It validates public `/` and `/chat`, separately authenticated `/fleet`, the exact `LFM3-1.7B` response envelope, rejection of unsupported tool/system-message fields, oversized prompts, and process-local HTTP 429 throttling. It shuts down both listeners after the test.

**This is a simulated demo only.** The fixture emits `4 [SIMULATED DEMO RESPONSE - NOT REAL MODEL INFERENCE]`; it does not download or run model weights. This acceptance proves only local Next.js, UI routing and API behavior, not production readiness, private-worker credentials, the Caddy/Nginx chain, Tailnet ACLs, distributed capacity, iOS device behavior, or real LFM3 generation.

For a *real* demo, run `deploy/lfm3/gateway-acceptance.mjs` against an approved, locally bound staging container after the secret mounts are provisioned. Require its `authenticated-staged-chat` PASS before considering any public cutover. Keep the existing production site and iOS TestFlight unchanged unless all release gates independently pass.
