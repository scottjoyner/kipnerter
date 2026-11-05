#!/usr/bin/env bash
# Read-only, single-purpose inventory. Runs as the authorized non-root
# kipnerter user on the production host over identity-verified Tailnet SSH.
set -euo pipefail
[[ "$(id -un)" == kipnerter ]] || { echo "HOLD: unexpected production principal"; exit 3; }
command -v docker >/dev/null || { echo "HOLD: Docker unavailable"; exit 3; }
command -v curl >/dev/null || { echo "HOLD: curl unavailable"; exit 3; }

container_state() {
  local name="$1" result
  result="$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)"
  case "$result" in
    true) echo running ;;
    false) echo stopped ;;
    *) echo absent ;;
  esac
}
http_code() {
  local url="$1" result
  result="$(curl --silent --output /dev/null --max-time 6 --write-out '%{http_code}' --noproxy '*' "$url" 2>/dev/null || true)"
  [[ "$result" =~ ^[0-9]{3}$ ]] && echo "$result" || echo "000"
}
public_web="$(container_state kipnerter-web-public-v01)"
legacy_stage="$(container_state kipnerter-lfm3-stage-5370ec1)"
new_stage="$(container_state kipnerter-lfm3-stage-rx480)"
local_home="$(http_code http://127.0.0.1:3355/)"
local_old="$(http_code http://127.0.0.1:3347/)"
# A bearer-protected real worker must refuse anonymous metadata requests.
# Do not send credentials, prompts, or any potentially private content.
worker_anonymous="$(http_code http://100.78.106.121:19176/v1/models)"

credential_state=not-running
if [[ "$new_stage" == running ]]; then
  # The script only checks metadata; it never opens or prints a token.
  credential_state="$(docker exec kipnerter-lfm3-stage-rx480 node -e '
    const fs=require("node:fs");
    const file="/run/secrets/kipnerter-lfm3/rx480.key";
    try {
      const s=fs.lstatSync(file);
      const good=s.isFile() && (s.mode & 0o077)===0 &&
        s.size>=16 && s.size<=2048;
      process.stdout.write(good ? "ready" : "invalid");
    } catch { process.stdout.write("missing"); }
  ' 2>/dev/null || echo unknown)"
  [[ "$credential_state" == ready || "$credential_state" == invalid ||
     "$credential_state" == missing ]] || credential_state=unknown
fi

echo "live_web_container=$public_web"
echo "prior_loopback_stage=$legacy_stage"
echo "single_rx480_stage=$new_stage"
echo "single_stage_http=$local_home"
echo "prior_stage_http=$local_old"
echo "rx480_anonymous_model_http=$worker_anonymous"
echo "rx480_key_metadata=$credential_state"
# No public routes, containers, model state or secret files have been changed.
echo "production_writes=none"
if [[ "$new_stage" != running || "$local_home" != 200 ||
      "$credential_state" != ready || "$worker_anonymous" != 401 ]]; then
  echo "HOLD: single-worker real staging is not fully admitted"
  exit 3
fi
echo "PASS: identity, gateway instance, protected key metadata, and worker ACL"
echo "HOLD: real authenticated HTTP generation still must pass release acceptance"
