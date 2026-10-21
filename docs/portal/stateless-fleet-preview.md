# Stateless fleet-chat preview — separate from state recovery

This is a **non-public, non-authorizing staging candidate** for web and control
API only. It is **not** a replacement for the production deployment workflow.
It cannot publish kipnerter.com/chat or satisfy live OIDC on its own.

The existing release workflow combines portal and spatial services, so MinIO
recovery holds that combined rollout. The stateless preview removes PostGIS,
MinIO and Caddy from its Compose service graph and refuses named volumes.
It is a distinct Compose project with only a loopback-bound web listener;
the API is reachable only inside that project's Docker network.

## Deny-only preview preflight (no containers started)

Run on a reviewed checkout with Docker Compose v2:

```sh
cd <reviewed-kipnerter-checkout>
export KIPNERTER_ENV=staging NEXTAUTH_URL=https://staging.kipnerter.com
set -o pipefail
docker compose -p kipnerter-fleet-preview -f docker-compose.yml -f compose.fleet-preview.yml config --format json \
  | python3 scripts/portal_fleet_preview_preflight.py
```

The validator checks the exact project, two fixed source build contexts,
local port 127.0.0.1:13300, no API host port, no privileged mounts, no
stateful service or volume, distinct networks and correct staging origin.
The JSON preflight never prints environment secret values. The output
always says `deployment_authorized=false` and `publicly_routable=false`.

**Do not run an unreviewed `up --remove-orphans`, bind 0.0.0.0,
enable Funnel, or repoint production Caddy.** No public ingress, real tsidp
client or authorized staging node was provisioned by this patch.

Promotion needs real browser identity/deny/expiry tests, private monitor
access, signed release approval, independently rehearsed rollback and
an explicitly authorized ingress change. Stateful spatial recovery remains
a separate gate for full production rollout, with preserved original data.

## Optional private Tailnet OIDC callback candidate (explicit opt-in)

A separately tested mode accepts **only** the exact Tailnet Serve origin
`https://x1-370.tailcb8954.ts.net:8449`, without changing the production
`https://kipnerter.com` or DNS staging `https://staging.kipnerter.com`
authorization origins. For a candidate Compose preflight only:

```sh
export KIPNERTER_ENV=tailnet-preview
export NEXTAUTH_URL=https://x1-370.tailcb8954.ts.net:8449
docker compose -p kipnerter-fleet-preview -f docker-compose.yml \
  -f compose.fleet-preview.yml config --format json | \
  python3 scripts/portal_fleet_preview_preflight.py
```

This mode is permitted only in the existing loopback-only preview graph;
production service identity, public DNS/ingress, Postgres/MinIO, and Caddy
remain out of scope. It remains `deployment_authorized=false` and
`oidc_real_login_verified=false`. Do **not** supply placeholder OIDC secrets.
Before real browser login, an authorized admin must independently approve
`tsidp` enrollment, capability grants, and a registered OIDC client whose
redirect is exactly
`https://x1-370.tailcb8954.ts.net:8449/api/auth/callback/tailscale`.
Keep client credentials in private non-repository storage and stage only after
review. Do not reuse a production client or silently switch from this opt-in
preview to the public ingress. No fake JWT proves live tsidp acceptance.
