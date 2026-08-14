# DigitalOcean Deployment

## Known account topology (2026-08-14)

### Project: current scottjoyner.dev resources

- Domain: `scottjoyner.dev`
- Droplet `ubuntu-s-2vcpu-4gb-nyc3-01`
  - NYC3
  - 4 GB RAM / 80 GB disk
  - IPv4 `143.198.19.141`
- Droplet `caddy`
  - NYC1
  - 1 GB RAM / 25 GB disk
  - IPv4 `143.244.166.142`

### Project: Personal Portfolio / kipnerter.com

Current observed DNS records supplied from the DigitalOcean control panel:

- `A kipnerter.com -> 143.244.166.142`
- `A app.kipnerter.com -> 165.227.81.99`
- `TXT _acme-challenge.kipnerter.com -> <existing ACME token>`

The apex therefore currently lands on the existing `caddy` droplet. Treat this as a live dependency until the replacement service is verified. Do not overwrite the apex or ACME record during foundation work.

## Recommended production target

Prefer the 4 GB NYC3 droplet (`143.198.19.141`) for the first complete Kipnerter application stack, subject to an inventory of what is already running there. The 1 GB `caddy` droplet can remain the existing edge during migration or be retired after traffic is cut over safely.

Target services:

- Caddy public edge
- Kipnerter web
- Kipnerter API
- lightweight queue/worker services where appropriate
- Tailscale client for private service connectivity

GPU inference, Neo4j datasets, Sophia/AssistX heavy workloads, and private MCP services should remain behind Tailscale unless there is a deliberate reason to host them in DigitalOcean.

## Pre-cutover checklist

1. Inventory running processes, containers, Caddy configuration, disk usage, firewall state, and Tailscale state on both droplets.
2. Snapshot/back up both droplets before destructive changes.
3. Confirm registrar nameserver delegation and export the current DNS zone.
4. Preserve all existing MX records before any nameserver migration. DigitalOcean only becomes authoritative after registrar delegation; missing MX records can interrupt mail.
5. Verify the `165.227.81.99` owner/service behind `app.kipnerter.com` before changing that record.
6. Deploy and validate web/API using a temporary hostname before apex cutover.
7. Add/verify Cloud Firewall rules: 80/443 public; SSH restricted to known management sources/Tailscale where feasible; application ports not exposed publicly.
8. Verify TLS and health probes.
9. Lower DNS TTL ahead of a planned cutover if faster rollback is desired.
10. Switch DNS only after smoke tests pass; retain a rollback path to `143.244.166.142`.

## DNS target (after validation)

A likely final topology is:

```text
kipnerter.com           -> production edge
www.kipnerter.com       -> production edge
api.kipnerter.com       -> production edge
scottjoyner.dev         -> production edge/admin UI
admin.scottjoyner.dev   -> production edge/admin UI
```

Actual A/AAAA values should not be changed until the target host has been inventoried and validated.

## Security baseline

- SSH key authentication only.
- Non-root sudo deployment user.
- Disable password root login.
- DigitalOcean Cloud Firewall in addition to host firewall controls.
- Enable monitoring; strongly consider backups/snapshots before migration.
- Secrets supplied at deploy time; never committed to GitHub.
- Tailscale for private east/west service access.
- No direct public exposure of Neo4j, Redis, LM Studio, Ollama, AssistX internal endpoints, or Sophia internal endpoints.
