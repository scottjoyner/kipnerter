# Read-only fleet questions (candidate)

This change makes the authenticated `/chat` workspace useful before model admission is approved.
It does **not** provision OIDC, publish the site, or authorize production release.

## Contract
- The question stays in the browser's React memory. No new HTTP endpoint, model call,
  persistent conversation, raw trace forwarding, or fleet execution capability exists.
- Only the five already-authenticated BFF projections are eligible:
  `overview`, `nodes`, `models`, `sessions`, and `traces`.
- Responses are deterministic, bounded summaries. Unknown, stale, and unavailable
  observer states cannot be reported as live. Browser receipt time is labeled as such.
- Mutating or execution-oriented prompts are refused. No shell, remote model admission,
  server-side LLM, or user-controlled destination is configured.
- LM Studio catalog and runtime-reported loaded instances remain **unverified**
  for independent residency or routing. Trace refresh is not proof of new execution.
- Authentication and session expiry remain enforced by the existing NextAuth app shell.
- Browser-native cloud spellcheck is not requested for sensitive fleet questions.

## Qualification
From `apps/web`: `node --test tests/*.test.mjs`, `npm run build`,
then `python3 ../../scripts/portal_e2e_smoke.py`.
All tests use synthetic credentials and avoid production writes.

## Remaining launch HOLD
Real Tailscale OIDC + signed-in browser acceptance, authorization for production SSH,
a dedicated staging-tagged host, MinIO image provenance and independently witnessed
PostGIS/MinIO isolated restoration must be separately completed before the full
portal release. This patch neither satisfies nor bypasses those requirements.
