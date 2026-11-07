# Tailnet-only HTTPS preview of the real LFM3 chat

**Operator validation:** November 5, 2026, directly on x1-370 with Fleet Commander. This is a private preview, not public production release.

## Live, verified path

- Browser: **https://x1-370.tailcb8954.ts.net:8450/chat** (requires an authorized Tailscale client and ACL for this node/port).
- API: `https://x1-370.tailcb8954.ts.net:8450/api/chat/completions` through the **real PR #96 Next.js server**, forwarding locally to the **official LFM3-1.7B Q4_K_M** model.
- Tailscale Serve HTTPS **8450** proxies only to `http://127.0.0.1:3357` on x1-370. The llama-server listener remains separately bound to `127.0.0.1:19181`; direct model access on the Tailnet IP fails, as intended.
- x1-370 private services are persistent enabled user-systemd units with `Restart=on-failure`, bounded CPU/memory/tasks, zero swap, checksum-pinned model and runtime, and startup admission checks.

## Actual network verification

1. The before snapshot of the node's Serve state contained HTTPS ports **443, 8443, 8445, 8446, 8447, 8448 and 8449**. Port 8450 was absent; no public Funnel route was configured.
2. Before changing Serve, the complete pre-existing **node status** was backed up to `/home/scott/.local/share/kipnerter-lfm3-fast/tailscale-serve-node-before-20261105.json` (private file, mode 0600). Note: `tailscale serve get-config --all` was not a usable backup of the existing node-wide Serve routing; use the before-status snapshot for inspection.
3. Ran **only** `tailscale serve --bg --https=8450 http://127.0.0.1:3357`. Compared the resulting Serve JSON to the original: **all seven existing HTTPS handlers and TCP port definitions are byte-for-byte equivalent after JSON parsing**. Exactly one new HTTPS origin and TCP port appeared; `AllowFunnel` remained unchanged.
4. Verified HTTPS from **Joyner and xwing** with the system TLS trust store: HTTP **200**, TLS verification result **0**, ~23–25 ms GET response. Both were reached using preexisting pinned ED25519 SSH host keys with strict checking.
5. From **xwing**, performed a *real* model-generated response through the new Tailnet HTTPS endpoint. HTTP **200**, model **LFM3-1.7B**, correct arithmetic output, **1,368 ms** for that one short request. No response text, session data, or credentials were logged.
6. Public `https://kipnerter.com/chat` still returned **404**. The direct model port `100.64.43.123:19181` was not reachable from outside x1's loopback.

**Not yet tested:** iOS Safari on a physical phone, broader phone Tailnet ACL permissions, true host reboot, public HTTPS release, concurrent-user p95 or production abuse controls. Do not call this public production.

## Single-port rollback (do not reset Tailscale Serve)

If the preview must be removed, from x1-370 use:

```bash
tailscale serve --https=8450 off
tailscale serve status --json
```

Inspect the new status against the saved before snapshot to confirm all seven preexisting HTTPS origins/handlers were preserved. **Do not run `tailscale serve reset` or modify the existing ports.** Stopping this preview does not stop the private LFM3 process or the production-host CPU fallback.

## Public release is separately gated

A public edge route would still require an reviewed private upstream path from the production Caddy container, authenticated access or independently validated anti-abuse controls, request size limits and IP identity/proxy header handling, bounded inference concurrency, user privacy, verified rollback, and live external HTTP 200 + real generation. The existing production Caddy instance runs inside Docker, and public `/chat` and `/api/chat/completions` return 404. **No public Caddy, DNS, protected RX480 credential, or TestFlight changes were made.**
