# Protected LFM3 public-HTTPS beta — live deployment evidence

**Date:** November 5, 2026. **Current status:** operator-authenticated preview **PASS**; general anonymous public release **HOLD**.

## Real deployed path

- **https://preview.kipnerter.com/chat** is a real external HTTPS endpoint, protected by Caddy HTTP Basic authentication (username `beta`).
- The running production `kipnerter-caddy-1` container proxies the authenticated request to `https://x1-370.tailcb8954.ts.net:8450`, which in turn proxies only to the local x1-370 Next.js app at `127.0.0.1:3357`. This app serves the official LiquidAI LFM3-1.7B Q4_K_M runtime at `127.0.0.1:19181`, with no direct public or Tailnet model port.
- The Caddy upstream HTTP Host is explicitly set to `x1-370.tailcb8954.ts.net:8450` for TLS/SNI compatibility. The certificate was verified. The production container itself previously fetched the private upstream with HTTP 200.
- `kipnerter.com` and `www.kipnerter.com` continue on the original public web image; `api.kipnerter.com` and `scottjoyner.dev` routing is unchanged.

## Credential handling

The beta uses a randomly generated 43-character operator password, held **only on the production host**, never in GitHub, tool output, client bundles, or public logs.

- Owner-only password: `/home/kipnerter/.local/state/lfm3-preview-20261105/preview.password`, mode **0600**.
- Caddy configuration contains only its Caddy-generated bcrypt hash; the password itself does not appear in the Caddyfile.
- To retrieve the beta password, use your **own authorized SSH/Tailscale shell** to read that path on `kipnerter-prod-01`. Do not paste it into GitHub or this chat. Browser login username: `beta`.

This authentication makes it an operator beta, **not** an anonymous public endpoint. Never claim Basic Auth alone is adequate anti-abuse protection for a general public LLM release.

## Verified live behavior

A separate Caddy canary ran with the **identical** authentication and proxy route, bound exclusively to the production host loopback at `127.0.0.1:18451`. It proved:

- No credentials: HTTP **401**; incorrect password: HTTP **401**.
- Valid credentials: real Next.js chat HTML **200**.
- Authenticated genuine `/api/chat/completions` call: **HTTP 200**, official model **LFM3-1.7B**, correct response in **1,678 ms**.

After canary acceptance, the Caddyfile was atomically replaced and the existing production Caddy reloaded **without restarting its container**. A post-reload actual model request passed in **1,464 ms**. `kipnerter.com/` stayed **200**, public `/chat` stayed **404**, and `api.kipnerter.com/health/ready` was **200**.

Additional audit:

- Anonymous `/`, `/chat`, `/api/chat/completions`, `/_next/static/__nonexistent-lfm3.js`: all **401**, with valid TLS.
- Wrong credential: **401**. Valid credential: HTML **200** and real CSS/JS `/_next/static` assets **200**.
- Independent no-write audit from pinned GitHub source: `PROTECTED_PREVIEW_LIVE_PASS`; actual end-to-end model response **1,474 ms**; no model response, password or hash printed.
- The temporary canary container was specifically identified, stopped, and removed after validation. The live preview stayed **401** anonymous; the original public site stayed **200**.

## Exact release artifacts, custody, rollback

On `kipnerter-prod-01`:

| Artifact | Location |
|---|---|
| Live Caddyfile | `/opt/kipnerter/infra/caddy/Caddyfile` |
| Owner-only password | `/home/kipnerter/.local/state/lfm3-preview-20261105/preview.password` |
| Original Caddyfile backup | `/home/kipnerter/.local/state/lfm3-preview-20261105/Caddyfile.before` |
| Reviewed deployed candidate | `/home/kipnerter/.local/state/lfm3-preview-20261105/Caddyfile.candidate` |

SHA-256 of **original** Caddyfile: `6713c86ef76caf2007f27f59482171efd082e2d6e8c023873748ea9ca523db68`.

SHA-256 of **deployed** Caddyfile: `6f24a5987968ac0ba12ca5895ee30e00744dd3bf4dd174c187432023606c255e`.

The deployed Caddy version was **v2.11.4**, image ID `sha256:df7f1c2fb114453b951de51a98efc010db1655a92c2e86be6706714e2417a78d`. Both candidate and canary configurations validated using that exact running image before deployment.

To roll back **only** the preview route after verifying these identities, stage the protected original Caddyfile backup into a temporary file in the same `/opt/kipnerter/infra/caddy` directory, preserve mode 0644, atomically rename to `Caddyfile`, then execute:

```bash
docker exec kipnerter-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Revalidate original external routes and preview. **Never** run a broad `docker compose down`, replace Caddy images, reset Tailscale Serve, publish x1-370 model port, or copy/bypass RX480 worker credentials.

## Repeatable read-only audit

The source-only `scripts/lfm3_protected_preview_audit.py` must be executed **on the authorized production host** as user `kipnerter`. It checks configuration hashes, password-file mode, running image identity, anonymous and wrong-password 401s, actual HTML/static assets, one real bounded model generation, plus unchanged public site and API health. It never prints credentials, prompts, model replies or authentication headers.

GitHub CI only compiles this auditor and tests its security contracts. **Hosted synthetic CI cannot replace direct production evidence.**

## Remaining production release gates

- **Anonymous public chat not released:** `https://kipnerter.com/chat` still 404. The old and new Next.js builds have different `/_next/static` assets, so blindly proxying only `/chat` would break browser resources.
- Stock Caddy v2.11.4 supports Basic Auth but **does not have a dedicated rate-limit handler** in the currently loaded module inventory. The app's process-local 8/minute defense and maxInflight=1 are **not** sufficient edge abuse controls for untrusted anonymous traffic.
- Need reviewed edge quotas, canonical client identity, request-size limits, fair concurrency, telemetry, origin privacy and reversible rollout before switching `kipnerter.com` to the new chat build. Consider a dedicated `chat.kipnerter.com` hostname only after authoritative DNS provisioning is verified.
- Physical Safari/ iPhone and native iOS/TestFlight remain unverified. The beta can now be tested from a regular browser after authorized login, without Tailscale on that device.
- Protected RX480 key remains unprovisioned and was not read or bypassed.
