#!/usr/bin/env bash
# Read-only production preflight. Never reads secrets, changes routes or launches models.
set -euo pipefail
[[ "$(id -un)" == kipnerter ]] || { echo "HOLD: wrong deployment principal"; exit 3; }
for cmd in docker curl python3; do command -v "$cmd" >/dev/null || { echo "HOLD: missing host tool"; exit 3; }; done
docker compose version >/dev/null || { echo "HOLD: missing Docker Compose"; exit 3; }
docker network inspect kipnerter_frontend >/dev/null 2>&1 ||
  { echo "HOLD: isolated gateway network not present"; exit 3; }
if docker container inspect kipnerter-lfm3-stage-rx480 >/dev/null 2>&1; then
  echo "HOLD: named staging container already exists (will not replace)"; exit 3
fi
port="$(curl --noproxy '*' -s -o /dev/null -m 4 -w '%{http_code}' http://127.0.0.1:3355/ || true)"
[[ "$port" == 000 || -z "$port" ]] ||
  { echo "HOLD: localhost stage port occupied"; exit 3; }
worker="$(curl --noproxy '*' -s -o /dev/null -m 6 -w '%{http_code}' http://100.78.106.121:19176/v1/models || true)"
[[ "$worker" == 401 ]] ||
  { echo "HOLD: RX480 worker unreachable or fails anonymous 401 authentication gate"; exit 3; }
free="$(df -Pk / | awk 'END{print $4}')"
ram="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
[[ "$free" =~ ^[0-9]+$ && "$ram" =~ ^[0-9]+$ ]] || exit 3
(( free >= 10000000 && ram >= 1000000 )) ||
  { echo "HOLD: gateway lacks resources for isolated stage"; exit 3; }
python3 - <<'PY'
import os,stat,sys
base="/home/kipnerter/.local/share/kipnerter-lfm3/secrets"
try:
    root=os.lstat(base)
    key=os.lstat(base+"/rx480.key")
    approved=(stat.S_ISDIR(root.st_mode) and root.st_uid in (0,os.getuid())
        and not(root.st_mode & 0o077) and stat.S_ISREG(key.st_mode)
        and key.st_uid in (0,os.getuid()) and not(key.st_mode & 0o077)
        and 16 <= key.st_size <= 2048)
except OSError:
    approved=False
if not approved:
    print("HOLD: production RX480 key is not approved/provisioned at protected mount")
    sys.exit(3)
print("PASS: protected RX480 key metadata; secret values never read")
PY
echo "PASS: production host ready for real isolated RX480 staging; writes=none"
