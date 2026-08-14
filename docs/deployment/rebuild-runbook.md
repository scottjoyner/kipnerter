# Kipnerter DigitalOcean rebuild runbook

This runbook treats the legacy DigitalOcean workloads as disposable after a final inventory/snapshot checkpoint. The accelerated path retains the existing 4 GB NYC3 Droplet and rebuilds it in place so its public IP stays `143.198.19.141`.

## Known legacy topology

| Resource | Current value | Intended disposition |
| --- | --- | --- |
| `caddy` droplet | `302306571` / `143.244.166.142` / NYC1 / 1 GB | retire after cutover |
| `ubuntu-s-2vcpu-4gb-nyc3-01` | `414171540` / `143.198.19.141` / NYC3 / 4 GB | rebuild in place as production |
| `kipnerter.com` apex | `143.244.166.142`, TTL 3600 | reduce TTL first; preserve until validation |
| `app.kipnerter.com` | `165.227.81.99` | inventory owner/workload before modifying |
| `_acme-challenge.kipnerter.com` | existing TXT record | preserve during migration |

DigitalOcean rebuilds preserve the Droplet's public IP while wiping/replacing its disk. Do **not** destroy Droplet `414171540` if we intend to retain `143.198.19.141`.

See `docs/deployment/dns-cutover.md` for the accelerated DNS procedure.

## Required secrets

Create GitHub Environments named `staging` and `production`. Require manual approval on `production` before deployment. Store these environment secrets rather than committing credentials:

- `DIGITALOCEAN_ACCESS_TOKEN`
- `TS_OAUTH_CLIENT_ID`
- `TS_OAUTH_SECRET`
- `KIPNERTER_DEPLOY_HOST` (MagicDNS hostname or Tailscale IP)
- `KIPNERTER_DEPLOY_USER` (`kipnerter` after bootstrap)

The Tailscale OAuth client used by GitHub CI must be allowed to create auth keys for `tag:kipnerter-ci`. Host provisioning should use a credential allowed to assign `tag:kipnerter-prod` and `tag:kipnerter-edge`.

## Phase 0: start DNS cache expiry and inspect

Before changing any IP target, edit the existing `kipnerter.com` apex record in DigitalOcean and reduce TTL from `3600` to `300` while leaving its value at `143.244.166.142`.

Create:

- `preview.kipnerter.com` A `143.198.19.141`, TTL `300`
- `api.kipnerter.com` A `143.198.19.141`, TTL `300` if absent

Do not change `app.kipnerter.com` or delete the ACME/MX/TXT records.

Then run the `infrastructure` workflow with `inventory`. Capture droplets, DNS, firewalls, volumes, images/snapshots, SSH keys and reserved IPs. On the retained 4 GB host also capture:

```bash
docker ps -a || true
docker images || true
docker volume ls || true
docker network ls || true
sudo ss -lntup
sudo systemctl --type=service --state=running
sudo crontab -l || true
sudo du -sh /var/lib/docker/* 2>/dev/null || true
sudo find /etc/caddy /opt /srv /var/www -maxdepth 3 -type f 2>/dev/null | sort
```

Archive only configs/data that are recognizable and still required.

## Phase 1: final snapshot and rebuild

Create a final named snapshot of Droplet `414171540` and record its snapshot ID. Then use DigitalOcean's **Rebuild / Restore base image** action to rebuild that same Droplet with a current Ubuntu LTS image.

Rebuild is intentionally different from destroy/recreate: the rebuild wipes the disk but preserves `143.198.19.141`.

After rebuild, its SSH host fingerprint will change. Bootstrap access using a registered DigitalOcean SSH key.

## Phase 2: bootstrap the production host

Run Ansible against the rebuilt host:

```bash
ansible-playbook -i '143.198.19.141,' -u root infra/ansible/playbooks/bootstrap.yml
ansible-playbook -i '143.198.19.141,' -u root infra/ansible/playbooks/tailscale.yml \
  -e "tailscale_auth_key=$TS_AUTHKEY"
```

Expected host state:

- `kipnerter` deployment user
- Docker Engine + Compose plugin
- Tailscale on the host
- `tag:kipnerter-prod` and `tag:kipnerter-edge`
- Tailscale SSH enabled
- repository cloned to `/opt/kipnerter`
- only 80/443 publicly exposed after Cloud Firewall activation

After Tailscale SSH is validated, remove public SSH ingress unless there is a documented break-glass CIDR.

## Phase 3: preview deployment

Deploy the edge stack:

```bash
cd /opt/kipnerter
docker compose --profile edge build
docker compose --profile edge up -d --remove-orphans
```

Validate:

- `https://preview.kipnerter.com`
- `https://api.kipnerter.com/health`
- `https://api.kipnerter.com/ready`
- Tailscale SSH
- GitHub Actions deployment connectivity

The repository Caddy config already accepts `preview.kipnerter.com`.

## Phase 4: establish persistent Terraform state and reconcile

CI deliberately cannot `terraform apply` yet. Before mutation, configure a persistent encrypted backend and import retained resources rather than recreating them.

For the retained 4 GB Droplet, the eventual import shape is:

```bash
terraform import digitalocean_droplet.prod 414171540
```

Only perform the import after `main.tf` is adjusted from the real account inventory so the subsequent plan does not replace the Droplet unexpectedly.

For an existing DNS zone that Terraform will manage later:

```bash
terraform import digitalocean_domain.kipnerter kipnerter.com
```

Import every retained DNS record before setting `manage_dns=true`.

## Phase 5: apex cutover

Only after preview/API health is green and the previous 3600-second TTL has had time to age out, change:

`kipnerter.com: 143.244.166.142 -> 143.198.19.141`

Keep TTL at `300` through the migration window. Use the `dns-preflight` workflow to compare Google and Cloudflare recursive resolver answers and display observed TTLs.

Leave the old Caddy host online throughout the rollback window.

## Phase 6: retire legacy edge

After the new deployment and DNS have remained healthy, use `infra/digitalocean/destroy-old-host.sh` against only the old Caddy Droplet. It requires a droplet-specific confirmation string and takes a final snapshot before deletion.

Example:

```bash
DROPLET_ID=302306571 \
CONFIRM_DESTROY=DESTROY-302306571 \
DIGITALOCEAN_ACCESS_TOKEN=... \
bash infra/digitalocean/destroy-old-host.sh
```

Never point the script at the retained production host.

## Rollback

Before the old Caddy host is retired, the fastest infrastructure rollback is DNS-first:

`kipnerter.com -> 143.244.166.142`

Application deployments use immutable Git SHAs and can also roll back on the new host:

```bash
ROLLBACK_SHA=<known-good-sha> bash scripts/rollback.sh
```
