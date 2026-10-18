# Authenticated Kipnerter fleet console

This is a staged, **fail-closed** implementation. Public `/chat` exists without requiring visitors to join the tailnet; no fleet data is available until an explicitly approved OIDC login succeeds.

## Identity boundary

- Use a reachable, trusted OIDC issuer (for example, the same upstream SSO provider used by Tailscale, or a deliberately published and protected `tsidp`).
- **Tailscale Serve identity headers are valid only for private Serve traffic.** Public Funnel/browser requests do not carry them. Never trust `Tailscale-User-Login` supplied directly by a public client.
- Configure `KIPNERTER_OIDC_ISSUER`, `KIPNERTER_OIDC_CLIENT_ID`, `KIPNERTER_OIDC_CLIENT_SECRET`, `NEXTAUTH_SECRET`, `KIPNERTER_ALLOWED_EMAILS`, `KIPNERTER_OPERATOR_EMAILS` and `NEXTAUTH_URL=https://kipnerter.com` only via deployment secrets.
- Browser JWT sessions are capped at eight hours. All console API traffic is served through Next.js session checks; the internal gateway bearer token stays server-side.
- No matching allowlisted email, missing provider config, no gateway key, or unavailable backend: **deny**, not fallback to public access.
- Only separately approved operators can inspect nodes or trace metadata.

## Staged capabilities

| Surface | Implementation | Activation |
| --- | --- | --- |
| /chat | Responsive chat-first Next.js route and OIDC login gate | Deploy web |
| Service overview | Read-only timed probes for AssistX, Sophia, Hermes, OpenCode, model runtime, monitor and trace reader | Configure each base URL |
| Model inventory | Actual authenticated provider `/v1/models`; discovery does not mean admitted/loaded | Configure LM Studio adapter |
| Chat | OpenAI-compatible completion via the existing exact-match gateway; not streaming or persistent | **Off by default**, see gate below |
| Nodes | Read-only Tailscale collector, only names and online state | Deploy private collector |
| Traces | Exact correlation-ID polling (10s), max 100 events, allowlisted metadata only | Configure read-only trace upstream/token |
| Tool sessions | Not exposed from web; no remote execution bridge | Future contract-reviewed integration |

**Chat execution HOLD:** `KIPNERTER_WEB_CHAT_ENABLED=false` until signed per-user admission, fencing, authorization, revocation, and receipts are verified end to end. Exposing LM Studio directly would otherwise bypass the router's execution controls. Do not enable simply because `/v1/models` is reachable. The current chat adapter is a staging integration, not the final AssistX execution path.

## Private collector

`apps/monitor/collector.py` runs beside a Tailscale client, with `FLEET_MONITOR_READ_TOKEN` set to a separate high-entropy read-only token. Run `uvicorn collector:app --host 127.0.0.1 --port 8769` from `apps/monitor`; publish *privately* with Tailscale Serve, not Funnel, and permit only the gateway's tagged identity to reach it. Give the API `FLEET_MONITOR_BASE_URL` and its token. The collector executes only a fixed `tailscale status --json` command with a five-second deadline and strips IPs and node metadata. The status view reports a node online only if Tailscale reports so.

## Verification and rollout

1. Run `cd apps/api && python3 -m pytest -q`, `cd apps/monitor && python3 -m pytest -q`, and `cd apps/web && npm ci && npm run build`.
2. Deploy the read-only app with `docker compose -f docker-compose.yml -f compose.console.yml up -d --build` using injected secrets and **chat disabled**.
3. Verify anonymous `GET /chat` only shows the login boundary. Verify all anonymous `/api/console/*` requests return 401/503 and authenticated nonoperator trace/node requests return 403.
4. Verify authorized SSO login and session expiry/revocation, actual tailnet gateway reachability, and zero private IP/credential leakage.
5. Validate observed services and model inventory against independent node witnesses. Validate trace metadata against known correlation IDs; raw payloads must remain inaccessible.
6. Only after physical end-to-end authorization receipts and rollback evidence should chat dispatch be considered for a separate approval.

The production host currently requires a Tailscale SSH authorization check, so this branch is not a production deployment.
