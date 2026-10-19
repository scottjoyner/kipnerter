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
