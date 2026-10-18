# Kipnerter unified fleet portal (operator MVP)

The public URL `https://kipnerter.com/chat` must exist, but it **never** serves
private fleet telemetry to anonymous visitors. The login landing page is safe
without any configured identity provider. Only a validated, allowlisted OIDC
identity can access `/api/portal/{overview,nodes,models,traces}`.

## Trust boundaries and required identities

1. **Browser → Next.js:** Tailscale-backed OIDC via separately deployed
   [tsidp](https://tailscale.com/docs/features/tsidp), with HTTPS issuer, PKCE/
   OAuth state handled by NextAuth, verified email, and explicit
   `KIPNERTER_ALLOWED_EMAILS` allowlist. `NEXTAUTH_SECRET` must be a fresh
   high-entropy secret (at least 32 chars). No browser localStorage credentials.
2. **Next.js → API:** server-side only, `http://api:8000`, using
   `KIPNERTER_GATEWAY_TOKEN`. All four portal endpoints reject missing/invalid
   credentials and return `Cache-Control: private, no-store`.
3. **API → private fleet:** explicit services configured via environment.
   AssistX read-only views use separate Basic credentials
   (`ASSISTX_MONITOR_USER`/`ASSISTX_MONITOR_PASSWORD`). Do not reuse privileged
   execution credentials. Traces project **only** ID, outcome, count, and timing:
   no prompts, addresses, payloads, or tokens.
4. **Tailscale node presence:** optional `tailnet_observer.py` on a trusted
   fleet node reads `tailscale status --json` without sudo, strips addresses
   and identifiers other than hostnames, binds only loopback, requires a
   separate `FLEET_MONITOR_TOKEN`, and permits only GET `/health` and
   `/v1/nodes`. Publish to **authorized peers only** using Tailscale Serve and
   grants; **never Tailscale Funnel**. API uses
   `FLEET_MONITOR_BASE_URL` (the Serve URL) and the monitor token.
5. A service health response is not admission, a model name is not a loaded
   model, and an AssistX node record is not verified Tailscale presence.

## Provisioning order

- Verify deployed platform branch and an independent production rollback.
- Set up `tsidp` on your tailnet, register the application callback
  `https://kipnerter.com/api/auth/callback/tailscale`, enable appropriate
  browser reachability (Tailscale client or intentionally exposed IdP via its
  own supported secure mode), and verify identity signing, redirect URI, and
  claims. `tsidp` is experimental; pin its version.
- Configure `TSIDP_ISSUER`, `TSIDP_CLIENT_ID`, `TSIDP_CLIENT_SECRET`,
  `NEXTAUTH_SECRET`, `NEXTAUTH_URL=https://kipnerter.com`,
  `KIPNERTER_ALLOWED_EMAILS` in GitHub deployment environment secrets.
  Without *all* values the portal fails closed and displays a setup notice.
- Provision read-only AssistX credentials independently and restrict their
  permissions to fleet/trace GET endpoints, then add their deployment secrets.
- On the trusted node run the observer with an independent 32+ char secret.
  Verify a denied unauthenticated GET, a permitted request with the observer
  token, and ACL denial from an unrelated node before configuring API access.
- Deploy to staging, validate access controls and SSE/event continuity before
  deploying to production. The portal has no direct agent execution endpoint.

## Read-only Hermes + OpenCode session integration

- The observer has a second bearer-protected `GET /v1/sessions` endpoint.
  It scans up to 5,000 local `fleet-agent-launcher` ledger entries with
  `O_NOFOLLOW`, file-size limits, job ID validation, and fail-closed parsing.
  It exports only IDs, agent type, status, requested model, timestamps, and
  verification/archival flags. No prompts, native session IDs, tokens, filesystem
  locations, full receipts, or raw agent traces are returned.
- The API exposes those projections under `/api/v1/control-plane/sessions`,
  and the authenticated web BFF under `/api/portal/sessions`.
- This first observer reports only launcher-managed sessions on the node hosting
  the observer; it is not yet a global multi-node OpenCode/Hermes inventory.
  `harvest_hold=true` means knowledge#173's archive hold is preserved.
- Run from the code checkout with `PYTHONPATH=apps/api
  python3 -m app.tailnet_observer`; the collector deliberately refuses
  non-loopback binding. Protect access over Tailscale Serve + scoped grants.

## Explicitly deferred

- Chat dispatch is **held**, not silently routed through unadmitted LM Studio
  or Router. Resume only after Auto-AssistX/Auto-Router demonstrates per-user
  identity, admitted loaded models, signed receipts, and failover fencing.
- Hermes, OpenCode, and Sophia currently expose health/configured status only.
  A dedicated user-scoped conversations, and shared trace
  identifiers need contract tests; no remote shell or command runner is
  exposed by this branch.
- Add event streams only after proving source authentication, bounded
  replay, per-user authorization, backpressure, and trace redaction.
- Avoid storing browser tokens or redisplaying arbitrary trace payloads.
