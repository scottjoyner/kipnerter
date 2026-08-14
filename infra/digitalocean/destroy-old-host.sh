#!/usr/bin/env bash
set -euo pipefail

: "${DIGITALOCEAN_ACCESS_TOKEN:?Set DIGITALOCEAN_ACCESS_TOKEN}"
: "${DROPLET_ID:?Set DROPLET_ID}"
: "${CONFIRM_DESTROY:?Set CONFIRM_DESTROY to DESTROY-${DROPLET_ID}}"

if [[ "$CONFIRM_DESTROY" != "DESTROY-${DROPLET_ID}" ]]; then
  echo "Refusing destruction: confirmation token must equal DESTROY-${DROPLET_ID}" >&2
  exit 2
fi

command -v doctl >/dev/null || { echo "doctl is required" >&2; exit 1; }

export DIGITALOCEAN_ACCESS_TOKEN

echo "Target droplet:"
doctl compute droplet get "$DROPLET_ID" --format ID,Name,PublicIPv4,Region,Size,Status

echo "Taking final snapshot before destruction..."
SNAPSHOT_NAME="pre-destroy-${DROPLET_ID}-$(date -u +%Y%m%dT%H%M%SZ)"
doctl compute droplet-action snapshot "$DROPLET_ID" --snapshot-name "$SNAPSHOT_NAME" --wait

echo "Snapshot complete: $SNAPSHOT_NAME"
echo "Destroying droplet $DROPLET_ID..."
doctl compute droplet delete "$DROPLET_ID" --force
