#!/usr/bin/env bash
# READ-ONLY-to-production research-only Nginx smoke check.
# Executes a temporary network-disabled container using an ALREADY-CACHED
# operator-approved immutable image. No Caddy reload, model traffic, credentials,
# host ports, persistent Docker volume, or image pull.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
image="${KIPNERTER_LFM3_EDGE_IMAGE:-}"
if [[ ! "$image" =~ @sha256:[a-f0-9]{64}$ ]]; then
  echo 'HOLD: set KIPNERTER_LFM3_EDGE_IMAGE to an approved immutable SHA256 digest' >&2
  exit 3
fi
if ! docker image inspect "$image" >/dev/null 2>&1; then
  echo 'HOLD: approved immutable image is not cached; no automatic pull performed' >&2
  exit 3
fi

runflags=(
  --network none
  --add-host kipnerter-lfm3-stage-provisioned:127.0.0.1
  --read-only
  --user 101:101
  --cap-drop ALL
  --security-opt no-new-privileges:true
  --tmpfs /tmp:rw,nosuid,nodev,size=16m,mode=1777
  --tmpfs /var/cache/nginx:rw,nosuid,nodev,size=16m,mode=1777
  --mount "type=bind,src=$root/nginx.conf,dst=/etc/nginx/nginx.conf,readonly"
  --entrypoint nginx
)

# Validate actual runtime syntax and permissions in a disposable container.
docker run --rm "${runflags[@]}" "$image" -t

name="kipnerter-lfm3-nginx-offline-canary-$$"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker run --detach --name "$name" "${runflags[@]}" "$image" -g 'daemon off;' >/dev/null

probe() {
  local mode="$1" route="$2" result
  if [[ "$mode" == POST ]]; then
    result="$(docker exec "$name" wget --post-data='{"messages":[{"role":"user","content":"4"}]}' -S -O /dev/null "http://127.0.0.1:8094$route" 2>&1 || true)"
  else
    result="$(docker exec "$name" wget -S -O /dev/null "http://127.0.0.1:8094$route" 2>&1 || true)"
  fi
  printf '%s\n' "$result" | grep -Eo 'HTTP/[0-9.]+[[:space:]]+[0-9]{3}' | tail -1 | awk '{print $2}'
}

if [[ "$(probe GET /)" != 404 ]]; then
  echo 'FAIL: unrelated path was not denied' >&2
  exit 2
fi
if [[ "$(probe GET /api/chat/completions)" != 405 ]]; then
  echo 'FAIL: only POST should be accepted on the chat path' >&2
  exit 2
fi
seen429=0
for _ in {1..12}; do
  status="$(probe POST /api/chat/completions || true)"
  if [[ "$status" == 429 ]]; then
    seen429=1
    break
  fi
  # The simulated upstream maps to an unavailable loopback host. HTTP 502
  # is expected before the shared limiter starts returning HTTP 429.
  if [[ "$status" != 502 ]]; then
    echo "FAIL: unexpected offline upstream response ${status:-none}" >&2
    exit 2
  fi
done
if [[ "$seen429" != 1 ]]; then
  echo 'FAIL: repeated requests did not trigger a shared HTTP 429' >&2
  exit 2
fi
echo 'PASS: isolated nginx syntax, GET denial, method restriction, and rate-limit 429'
echo 'No real gateway, model endpoint, Caddy route, or secret was contacted.'
