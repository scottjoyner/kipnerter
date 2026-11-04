#!/usr/bin/env bash
# Real web HTTP checks against *simulated* Docker-only local model.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${KIPNERTER_LFM3_DEMO_PORT:-3360}"
BASE="http://127.0.0.1:${PORT}"
if ! [[ "$PORT" =~ ^[0-9]{2,5}$ ]]; then
  echo "Invalid local demo port" >&2
  exit 2
fi
curl_opts=(--silent --show-error --fail --max-time 4)
ready=0
for attempt in $(seq 1 60); do
  if page="$(curl "${curl_opts[@]}" "$BASE/chat" 2>/dev/null)" && grep -q 'Message Kipnerter' <<<"$page"; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" != 1 ]]; then echo 'Local Docker demo is not ready' >&2; exit 1; fi
for route in / /chat; do
  page="$(curl "${curl_opts[@]}" "$BASE$route")"
  grep -q 'Message Kipnerter' <<<"$page"
  grep -q 'LFM3-1.7B' <<<"$page"
  if grep -q 'Sign in with Tailscale identity' <<<"$page"; then
    echo "Operator login leaked into $route" >&2; exit 1
  fi
done
fleet="$(curl "${curl_opts[@]}" "$BASE/fleet")"
grep -q 'PRIVATE AI WORKSPACE' <<<"$fleet"
response="$(curl "${curl_opts[@]}" -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"What is 2 + 2?"}]}' \
  "$BASE/api/chat/completions")"
python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d.get("model")=="LFM3-1.7B"
assert "4 " in d.get("reply","")
assert "SIMULATED DEMO RESPONSE" in d.get("reply","")
print("PASS: real Next.js / and /chat, protected /fleet, simulated HTTP model reply")
' <<<"$response"
code="$(curl --silent --output /dev/null --write-out '%{http_code}' -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"system","content":"not allowed"}]}' \
  "$BASE/api/chat/completions")"
[[ "$code" = 400 ]] || { echo "system-role rejection got $code" >&2; exit 1; }
echo "SIMULATED_ONLY=true; HOST_LOOPBACK=true; NO_REAL_MODEL_OR_FLEET_CREDENTIALS=true"
