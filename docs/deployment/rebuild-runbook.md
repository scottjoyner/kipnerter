# Kipnerter DigitalOcean rebuild runbook

This runbook treats the legacy DigitalOcean workloads as disposable after a final inventory/snapshot checkpoint. Do not delete DNS zones, snapshots, volumes, or droplets until the current service inventory has been captured.

## Known legacy topology

| Resource | Current value | Intended disposition |
| --- | --- | --- |
| `caddy` droplet | `302306571` / `143.244.166.142` / NYC1 / 1 GB | retire after cutover |
| `ubuntu-s-2vcpu-4gb-nyc3-01` | `414171540` / `143.198.19.141` / NYC3 / 4 GB | preferred first production host or rebuild target |
| `kipnerter.com` apex | `143.244.166.142` | preserve until new edge passes validation |
| `app.kipnerter.com` | `165.227.81.99` | inventory owner/workload before modifying |
| `_acme-challenge.kipnerter.com` | existing TXT record | preserve during migration |

## Required secrets

Create GitHub Environments named `staging` and `production`. Require manual approval on `production` before deployment. Store these environment secrets rather than committing credentials:

- `DIGITALOCEAN_ACCESS_TOKEN`
- `TS_OAUTH_CLIENT_ID`
- `TS_OAUTH_SECRET`
- `KIPNERTER_DEPLOY_HOST` (MagicDNS hostname or Tailscale IP)
- `KIPNERTER_DEPLOY_USER` (`kipnerter` after bootstrap)

The Tailscale OAuth client used by GitHub CI must be allowed to create auth keys for `tag:kipnerter-ci`. Host provisioning should use a credential allowed to assign `tag:kipnerter-prod` and `tag:kipnerter-edge`.

## Phase 0: inspect only

Run the `infrastructure` workflow with `inventory`. Capture droplets, DNS, firewalls, volumes and reserved IPs. On each legacy host also capture:

```bash
docker ps -a
docker images
docker volume ls
docker network ls
sudo ss -lntup
sudo systemctl --type=service --state=running
sudo crontab -l || true
sudo du -sh /var/lib/docker/* 2>/dev/null || true
sudo find /etc/caddy /opt /srv /var/www -maxdepth 2 -type f 2>/dev/null | sort
```

Archive only configs/data that are recognizable and still required.

## Phase 1: establish persistent Terraform state

CI deliberately cannot `terraform apply` yet. Before mutation, configure a persistent encrypted remote backend and import any existing DigitalOcean resources that will be retained. Do not keep state as a GitHub artifact or commit it to the repository.

For the current 4 GB droplet, the eventual import shape is:

```bash
terraform import digitalocean_droplet.prod 414171540
```

Only perform the import after `main.tf` is adjusted to match the retained host closely enough that the next plan does not replace it unexpectedly.

For an existing DNS zone that Terraform will manage later:

```bash
terraform import digitalocean_domain.kipnerter kipnerter.com
```

Import every DNS record that must survive before setting `manage_dns=true`.

## Phase 2: bootstrap the production host

Run Ansible against the selected/rebuilt host:

```bash
ansible-playbook -i '<host>,' -u root infra/ansible/playbooks/bootstrap.yml
ansible-playbook -i '<host>,' -u root infra/ansible/playbooks/tailscale.yml \
  -e "tailscale_auth_key=$TS_AUTHKEY"
```

After Tailscale SSH is validated, remove public SSH ingress from the DigitalOcean Cloud Firewall unless there is a documented break-glass CIDR.

Clone this repository to `/opt/kipnerter`, configure production secrets outside git, and validate:

```bash
docker compose --profile edge build
docker compose --profile edge up -d
curl -fsS https://api.kipnerter.com/health
```

Do not change the apex DNS record until a temporary hostname or direct-host test proves Caddy, web and API health.

## Phase 3: DNS cutover

1. Reduce TTL ahead of the cutover when practical.
2. Confirm MX/TXT/verification records are preserved.
3. Point `api.kipnerter.com` and a temporary validation hostname to the new edge first.
4. Validate TLS, web, API, WebSocket/SSE paths and Tailscale-only upstream services.
5. Change the `kipnerter.com` apex only after validation.
6. Leave the old edge online through the rollback window.

## Phase 4: retire legacy hosts

After the new deployment and DNS have remained healthy, use `infra/digitalocean/destroy-old-host.sh`. It requires a droplet-specific confirmation string and takes a final snapshot before deletion.

Example:

```bash
DROPLET_ID=302306571 \
CONFIRM_DESTROY=DESTROY-302306571 \
DIGITALOCEAN_ACCESS_TOKEN=... \
bash infra/digitalocean/destroy-old-host.sh
```

Never point the script at the active production host. Terraform's production resource also has `prevent_destroy = true` as an independent safety rail.

## Rollback

Deployments use immutable Git SHAs. To roll back on the host:

```bash
ROLLBACK_SHA=<known-good-sha> bash scripts/rollback.sh
```

During DNS migration, the fastest infrastructure rollback is to restore the previous A record while the legacy edge is still alive.
