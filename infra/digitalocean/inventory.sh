#!/usr/bin/env bash
set -euo pipefail

: "${DIGITALOCEAN_ACCESS_TOKEN:?Set DIGITALOCEAN_ACCESS_TOKEN}"

export DIGITALOCEAN_ACCESS_TOKEN

command -v doctl >/dev/null || { echo "doctl is required" >&2; exit 1; }

printf '\n== Account ==\n'
doctl account get
printf '\n== Droplets ==\n'
doctl compute droplet list
printf '\n== Firewalls ==\n'
doctl compute firewall list || true
printf '\n== Volumes ==\n'
doctl compute volume list || true
printf '\n== Reserved IPs ==\n'
doctl compute reserved-ip list || true
printf '\n== Domains ==\n'
doctl compute domain list

for domain in kipnerter.com scottjoyner.dev; do
  printf '\n== DNS: %s ==\n' "$domain"
  doctl compute domain records list "$domain" || true
done

printf '\nInventory complete. No resources were modified.\n'
