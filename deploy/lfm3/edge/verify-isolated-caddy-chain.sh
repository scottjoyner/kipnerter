#!/usr/bin/env bash
# Network-isolated Caddy -> Nginx spoofed forwarded-header regression.
# Temporary containers, no host ports, no real gateway, models or credentials.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
nginx_image="$(printenv KIPNERTER_LFM3_EDGE_IMAGE || true)"
caddy_image="$(printenv KIPNERTER_LFM3_CADDY_IMAGE || true)"
[[ "$nginx_image" =~ @sha256:[a-f0-9]{64}$ ]] || {
  echo "HOLD: immutable Nginx digest required" >&2; exit 3;
}
[[ "$caddy_image" =~ ^sha256:[a-f0-9]{64}$ ]] || {
  echo "HOLD: local Caddy image ID required" >&2; exit 3;
}
docker image inspect "$nginx_image" "$caddy_image" >/dev/null 2>&1 || {
  echo "HOLD: both images must already be cached" >&2; exit 3;
}
candidate="$here/../caddy.phase1.candidate.Caddyfile"
grep -Fq 'reverse_proxy 127.0.0.1:8094' "$candidate"
grep -Fq 'header_up X-Forwarded-For {remote_host}' "$candidate"
grep -Fq 'header_up X-Real-IP {remote_host}' "$candidate"
grep -Fq 'host kipnerter.com' "$candidate"

scratch="$(mktemp -d /tmp/lfm3-offline-caddy-chain-XXXXXX)"
caddy="lfm3-offline-caddy-$$"
nginx="lfm3-offline-nginx-$$"
cleanup() {
  docker rm -f "$nginx" "$caddy" >/dev/null 2>&1 || :
  rm -rf -- "$scratch"
}
trap cleanup EXIT
sed 's|proxy_pass http://kipnerter-lfm3-stage-provisioned:3000;|proxy_pass http://127.0.0.1:59999;|' \
  "$here/nginx.conf" >"$scratch/nginx.conf"
grep -Fq 'proxy_pass http://127.0.0.1:59999;' "$scratch/nginx.conf"

# HTTP-only test listener. Mirrors only canonical host/path and trusted
# forwarded-header behavior of the reviewed, unapplied Caddy candidate.
cat >"$scratch/Caddyfile" <<'CADDY'
{
    auto_https off
}
http://:18111 {
    @canonical_lfm3_chat {
        host kipnerter.com
        path /api/chat/completions
        method POST
    }
    handle @canonical_lfm3_chat {
        request_body {
            max_size 8KB
        }
        reverse_proxy 127.0.0.1:8094 {
            header_up X-Forwarded-For {remote_host}
            header_up X-Real-IP {remote_host}
        }
    }
    handle { respond "Not found" 404 }
}
CADDY
docker run -d --name "$caddy" --network none --read-only \
  --cpus 0.2 --memory 96m --pids-limit 30 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,size=8m,mode=1777 \
  --tmpfs /config:rw,nosuid,nodev,size=8m \
  --tmpfs /data:rw,nosuid,nodev,size=8m \
  --mount "type=bind,source=$scratch/Caddyfile,target=/etc/caddy/Caddyfile,readonly" \
  --entrypoint caddy "$caddy_image" run --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

for _ in 1 2 3 4 5; do
  running="$(docker inspect -f '{{.State.Running}}' "$caddy")"
  if [[ "$running" != true ]]; then
    echo "FAIL: offline Caddy exited" >&2
    docker logs --tail 14 "$caddy" >&2
    exit 2
  fi
  probe="$(docker exec "$caddy" curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:18111/ || true)"
  if [[ "$probe" == 404 ]]; then break; fi
  sleep 1
done
docker run -d --name "$nginx" --network "container:$caddy" \
  --read-only --user 101:101 --cpus 0.2 --memory 64m --pids-limit 30 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,size=8m,mode=1777 \
  --tmpfs /var/cache/nginx:rw,nosuid,nodev,size=8m,mode=1777 \
  --mount "type=bind,source=$scratch/nginx.conf,target=/etc/nginx/nginx.conf,readonly" \
  --entrypoint nginx "$nginx_image" -g 'daemon off;' >/dev/null
status() {
  local method="$1" host="$2" forged="$3"
  docker exec "$caddy" curl -s -o /dev/null -w '%{http_code}' --max-time 4 \
    -X "$method" -H "Host: $host" \
    -H "X-Real-IP: $forged" -H "X-Forwarded-For: $forged" \
    -H 'Content-Type: application/json' \
    --data '{"messages":[{"role":"user","content":"4"}]}' \
    http://127.0.0.1:18111/api/chat/completions
}
wrong="$(status POST preview.kipnerter.com 192.0.2.11)"
[[ "$wrong" == 404 ]] || { echo "FAIL: noncanonical host was routed: $wrong" >&2; exit 2; }
# Each attempt forges a different originating client. The Caddy-overwritten
# address should force them into ONE per-client bucket. The fourth response
# must be 429 (earlier than the independent global limiter would trigger).
for i in 1 2 3 4 5; do
  code="$(status POST kipnerter.com "198.51.100.$i")"
  echo "SPOOFED_HEADER_ATTEMPT_$i=$code"
  case "$i" in
    1|2|3) [[ "$code" == 502 ]] || { echo "FAIL: unexpected offline upstream response" >&2; exit 2; };;
    4|5) [[ "$code" == 429 ]] || { echo "FAIL: forwarded-IP limit bypass" >&2; exit 2; };;
  esac
done
echo "PASS: isolated Caddy->Nginx canonical host, forwarded IP overwrite and per-client rate limit"
echo "No public route, real model, token or gateway contacted."
