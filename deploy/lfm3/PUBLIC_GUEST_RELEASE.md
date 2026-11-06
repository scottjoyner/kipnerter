# Public LFM3-1.7B guest chat — live bounded rollout

**Deployment:** November 5, 2026, using Fleet Commander read/write access to the original production host. **This is an actual live feature**, not a simulator, with deliberately strict low-volume beta quotas.

## Public user experience and isolation

- Entry point: **https://kipnerter.com/chat** (HTTP 302 to **https://preview.kipnerter.com/chat**).
- Guest chat and its necessary Next.js static assets can be viewed **without a password**.
- POST to `https://preview.kipnerter.com/api/chat/completions` goes through the production Caddy container, a dedicated Nginx rate/concurrency gate, Tailscale Serve HTTPS, the x1-370 Next.js application, and the official local **LFM3-1.7B Q4_K_M** model.
- The **operator homepage**, **/fleet**, and private API paths (including `/api/chat/fleet-status`) remain behind the pre-existing Basic Auth rule. The operator password was **not altered or published**.
- `https://kipnerter.com/` still uses its original public web image. `api.kipnerter.com/health/ready` still returns 200; the production-host CPU staging fallback and protected RX480 key were not modified.

## Rate and resource caps

Dedicated gateway: Docker `kipnerter-lfm3-public-gate-v01`, exact cached Nginx 1.30.6 image **sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949**.

- 160 MiB memory hard limit, 0.4 CPU, 64 processes, read-only root filesystem, unprivileged uid/gid **101:101**, all capabilities dropped, `no-new-privileges`, bounded tmpfs, `restart=unless-stopped`.
- No Docker host-published ports. Gateway is reachable only through the existing internal `kipnerter_frontend` bridge; the production Caddy overwrites `X-Kipnerter-Client-IP` with its canonical TCP remote host, rather than trusting a browser-supplied header.
- Per-client: **3 POST requests/minute**, initial burst allowance of **2**; global: **12 POST requests/minute**, burst allowance of **4**. A separate global **one-concurrent-inference** gate. Excess requests return **HTTP 429**.
- API accepts POST only, bodies maximum **8192 bytes**; oversized bodies return **413**, absent internal trusted identity **403**. The Next.js handler also retains its own payload, context, request and process-local defenses.
- Upstream TLS is verified with a pin-checked copy of the production host CA bundle. Tailscale certificate currently has a four-level chain; Nginx sets `proxy_ssl_verify_depth 6` in **both** its API and HTML/asset proxy blocks. Never set `proxy_ssl_verify off`.
- No request or model-response body access logs are enabled in Nginx. The model port on x1-370 remains localhost-only; only Tailscale Serve can access the frontend.
- This is a deliberately **small capacity** public beta. It is not proof of large-scale DDoS resistance or production p95/availability. Client-IP quotas can be shared by NAT users; the independent global cap preserves the resource ceiling.

## Live execution and negative tests

Before publication an isolated Nginx container bound only on host loopback port **18453** was used to verify: genuine Next.js HTML 200; missing trusted identity 403; wrong method 403; oversized 9 KB body 413; actual official model completion HTTP 200 in **1946 ms**; a same-client burst produced **400, 400, 429, 429**. The Caddy integration canary, bound only on host loopback **18454**, verified anonymous chat HTML and CSS/JS assets 200, protected operator root 401, genuine model response 200 in **1536 ms**, and same-client burst **400, 400, 429, 429**.

The final Caddyfile was atomically promoted with a guarded rollback and gracefully reloaded in the **existing** production Caddy container (no restart). Independent public checks then returned:

| Path | Expected and observed |
|---|---|
| `kipnerter.com/` | **200** |
| `kipnerter.com/chat` | **302**, redirect to public guest |
| `preview.kipnerter.com/chat` | **200**, no credentials |
| `preview.kipnerter.com/_next/static/…` (real assets) | **200** |
| `preview.kipnerter.com/api/chat/completions` | Real LFM3 response **200**, **2117 ms** |
| `preview.kipnerter.com/` | **401**, operator-only |
| `preview.kipnerter.com/fleet` and `/api/chat/fleet-status` | **401**, operator-only |
| `api.kipnerter.com/health/ready` | **200** |

Additional public POST requests returned **400, 400, 400, 429, 429, 429**, confirming the rate gate is active from an independent Tailnet client. A subsequent exact-source **read-only** production audit returned `PUBLIC_GUEST_LFM3_RELEASE_PASS` with another real generation in **1711 ms**. Four short model timings are individual observations, not a p95 or SLO.

## Files and exact rollback IDs

All runtime release files are scoped to `/home/kipnerter/.local/state/lfm3-public-edge-gate-20261105`.

| Runtime artifact | SHA-256 |
|---|---|
| Original protected Caddyfile, `Caddyfile.before` | `2e4ba38cd67316b6469c740aee7fc4e19b9c2cc3754a1a2a92b00bb01819d23a` |
| Current guest Caddyfile, `Caddyfile.public-candidate` | `0788282cee590569e2a519678cc9cb4afa02c61ce29813ce27b70e1878635471` |
| Nginx rate gateway, `nginx.conf.prod` | `17c7b5033d000547a79917f63235675bad038bb24cc02e0d920320bd69d9bc85` |
| Trust bundle, `verified-host-ca.pem` | `0e4c9a8eb123513b1c131c0aec2d3f9ddaad02b77b8af53bff30e1e7fc3c6b71` |

**Emergency rollback:** First verify the live Caddyfile SHA is the known deployed SHA and the backup SHA is the known prior SHA. Copy the backup's bytes into a temporary file **in the existing production Caddyfile directory**, set mode 0644, atomically replace `/opt/kipnerter/infra/caddy/Caddyfile`, and call:

```bash
docker exec kipnerter-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Verify `kipnerter.com/` remains **200**, `kipnerter.com/chat` still redirects to the protected beta, and unauthenticated `preview.kipnerter.com/chat` reverts to **401**. Only after the previous Caddy route is restored, the `kipnerter-lfm3-public-gate-v01` container may be stopped if desired. **Do not** restart the original x1 inference model, delete credentials, reset Tailscale Serve, remove production networks, or touch the RX480 protected key. Never upload the actual live Caddyfile: it contains the operator bcrypt hash.

## Repeatable proof

Run `scripts/lfm3_public_guest_audit.py` on `kipnerter-prod-01` as `kipnerter`. It verifies hardcoded release SHA identities, gateway Docker isolation/resource limits, TLS policy, exact public/private route boundaries, Next.js assets, and **one bounded real-model answer**. No credentials or response text are printed. The GitHub CI contract tests only source policies and syntax; it does not reach the production host.

## Outstanding gates

Native physical iPhone Safari has **not** been operated; testing an iPhone User-Agent from the fleet returned HTTP 200 but is not a device test. The iOS app's signing, build disk-space and TestFlight gates remain separate. Full x1-370 reboot recovery has not been tested; controlled service restart and SIGKILL recovery were verified in the preceding stage. Larger-scale concurrency/performance and external abuse-resilience evaluation are still needed before removing low-volume beta quotas.
