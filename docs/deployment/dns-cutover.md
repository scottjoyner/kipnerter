# DNS cutover: fastest safe path

## Goal

Retain the existing 4 GB NYC3 Droplet (`414171540`, `143.198.19.141`) as the Kipnerter production host, rebuild its disk in place, validate through `preview.kipnerter.com`, then move the public apex with a short DNS TTL.

A DigitalOcean Droplet rebuild preserves the Droplet's public IP while replacing the disk image. Do not destroy this Droplet if preserving `143.198.19.141` matters.

## Phase 0 — start cache expiry now

In the DigitalOcean DNS zone for `kipnerter.com`:

1. Leave the current apex value unchanged (`kipnerter.com -> 143.244.166.142`).
2. Change the apex TTL from `3600` to `300`.
3. Create `preview.kipnerter.com` as an A record to `143.198.19.141`, TTL `300`.
4. Create `api.kipnerter.com` as an A record to `143.198.19.141`, TTL `300` if it does not already exist.
5. Do not modify `app.kipnerter.com` yet.
6. Do not remove `_acme-challenge.kipnerter.com`.
7. Preserve every MX/TXT record in the zone.

Changing the apex TTL does not immediately invalidate resolver caches that already observed the old TTL. Allow up to the previous 3600-second TTL for those caches to age out before relying on a five-minute cutover window.

## Phase 1 — snapshot and rebuild the retained host

Before rebuild:

- run the read-only cloud inventory workflow
- inventory host services and Docker volumes
- create a DigitalOcean snapshot of Droplet `414171540`
- record the snapshot ID
- verify console/SSH access path

Then rebuild Droplet `414171540` using a current Ubuntu LTS image. Rebuild, do not destroy/recreate, because destroying releases the current public IPv4 address.

After rebuild:

- bootstrap the `kipnerter` deployment user
- install Docker and Tailscale
- attach the host as `tag:kipnerter-prod` / `tag:kipnerter-edge`
- enable Tailscale SSH
- clone this repository to `/opt/kipnerter`
- deploy the edge profile
- apply the DigitalOcean Cloud Firewall after confirming Tailscale connectivity

## Phase 2 — validate before apex cutover

Validate all of the following through `143.198.19.141` / the preview hostname:

- `https://preview.kipnerter.com`
- `https://api.kipnerter.com/health`
- `https://api.kipnerter.com/ready`
- web -> API connectivity
- Tailscale SSH from an administrative node
- GitHub Actions -> Tailscale -> production host deployment connectivity
- certificate issuance and renewal path

Do not move the apex until preview and API are healthy.

## Phase 3 — apex cutover

Change only the apex A record:

`kipnerter.com: 143.244.166.142 -> 143.198.19.141`

Keep TTL at 300 during the migration window.

Then validate using multiple resolvers and networks. Leave the old Caddy Droplet online until the previous 3600-second cache window plus an operational safety margin has elapsed.

## Phase 4 — stabilization

When traffic is consistently reaching `143.198.19.141`:

- verify `www.kipnerter.com`
- verify `api.kipnerter.com`
- verify `preview.kipnerter.com`
- confirm no requests depend on `app.kipnerter.com`
- increase stable DNS TTL later (for example 1800-3600)
- snapshot the old Caddy Droplet
- retire old Droplet `302306571` only after rollback is no longer required

## Rollback

If the new host is unhealthy after the apex move, restore the apex A record to `143.244.166.142`. With caches already aged down to the 300-second TTL, most compliant resolvers should refresh on approximately that cadence, though resolver behavior is not guaranteed.

Never destroy the old Caddy host until rollback is no longer needed.
