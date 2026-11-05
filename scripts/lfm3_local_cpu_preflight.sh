#!/usr/bin/env bash
# READ ONLY: no model, container, credential, Caddy, user file or port mutation.
set -euo pipefail
[[ "$(id -un)" == kipnerter ]] || { echo "HOLD: wrong production user"; exit 3; }
for tool in docker curl python3 sha256sum; do
  command -v "$tool" >/dev/null || { echo "HOLD: essential host tool missing"; exit 3; }
done
docker compose version >/dev/null || { echo "HOLD: Docker Compose unavailable"; exit 3; }
for name in kipnerter-lfm3-local-cpu kipnerter-lfm3-local-web; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    echo "HOLD: isolated local CPU stage already exists; no replacement"; exit 3
  fi
done
port="$(curl --noproxy '*' -s -o /dev/null -m 4 -w '%{http_code}' http://127.0.0.1:3356/ || true)"
[[ "$port" == 000 || -z "$port" ]] || { echo "HOLD: staging port 3356 occupied"; exit 3; }
disk="$(df -Pk / | awk 'END{print $4}')"
ram="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
[[ "$disk" =~ ^[0-9]+$ && "$ram" =~ ^[0-9]+$ ]] || exit 3
echo "gateway_available_kib=$ram"
echo "gateway_disk_free_kib=$disk"
(( disk >= 10000000 && ram >= 2200000 )) ||
  { echo "HOLD: preserving 4GiB production host; insufficient spare RAM/disk"; exit 3; }
echo "PASS: safe to attempt 1536MiB-model + 384MiB-web bounded stage (no public exposure)"
