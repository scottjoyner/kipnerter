#!/usr/bin/env bash
# Exact-source, localhost-only REAL RX480 Next.js stage. No Caddy/Apple mutations.
set -euo pipefail
[[ "$(id -un)" == kipnerter ]] || { echo "HOLD: wrong deployment principal"; exit 3; }
[[ $# -eq 3 ]] || { echo "HOLD: expected SHA, image digest, run ID"; exit 3; }
SHA="$1"; EXPECTED_ID="$2"; RUN="$3"
[[ "$SHA" =~ ^[a-f0-9]{40}$ && "$EXPECTED_ID" =~ ^sha256:[a-f0-9]{64}$ &&
   "$RUN" =~ ^[0-9]{8,14}$ ]] || { echo "HOLD: invalid release identities"; exit 3; }
STAGEDIR="/home/kipnerter/.local/state/kipnerter-lfm3/rx480/$SHA-$RUN"
MANIFEST="$STAGEDIR/compose.staging.rx480.yml"
SECRET_DIR="/home/kipnerter/.local/share/kipnerter-lfm3/secrets"
IMAGE="kipnerter-lfm3-stage-rx480:$SHA"
[[ -f "$MANIFEST" && ! -L "$MANIFEST" ]] || { echo "HOLD: missing reviewed stage manifest"; exit 3; }
actual="$(docker image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || true)"
[[ "$actual" == "$EXPECTED_ID" ]] || { echo "HOLD: deployed image digest mismatch"; exit 3; }
docker network inspect kipnerter_frontend >/dev/null 2>&1 ||
  { echo "HOLD: isolated network missing"; exit 3; }
if docker container inspect kipnerter-lfm3-stage-rx480 >/dev/null 2>&1; then
  echo "HOLD: existing stage will never be replaced"; exit 3
fi
python3 - <<'PY'
import os,stat,sys
root="/home/kipnerter/.local/share/kipnerter-lfm3/secrets"
try:
    r=os.lstat(root); s=os.lstat(root+"/rx480.key")
    ok=(stat.S_ISDIR(r.st_mode) and not(r.st_mode&0o077) and
        stat.S_ISREG(s.st_mode) and not(s.st_mode&0o077) and
        s.st_uid in (0,os.getuid()) and 16<=s.st_size<=2048)
except OSError: ok=False
if not ok: print("HOLD: protected key metadata not ready"); sys.exit(3)
PY
export KIPNERTER_LFM3_STAGE_IMAGE="$IMAGE"
export KIPNERTER_LFM3_SECRET_DIR="$SECRET_DIR"
docker compose -p kipnerter-lfm3-rx480 -f "$MANIFEST" config --quiet

# On any failed real acceptance, remove only the instance with both the
# expected Compose project label and immutable built-image identity.
rollback() {
  local id="" project="" image=""
  id="$(docker inspect --format '{{.Id}}' kipnerter-lfm3-stage-rx480 2>/dev/null || true)"
  if [[ "$id" =~ ^[a-f0-9]{64}$ ]]; then
    project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$id" 2>/dev/null || true)"
    image="$(docker inspect --format '{{.Image}}' "$id" 2>/dev/null || true)"
    if [[ "$project" == kipnerter-lfm3-rx480 && "$image" == "$EXPECTED_ID" ]]; then
      docker rm -f "$id" >/dev/null 2>&1 || true
      echo "ROLLBACK: only failed isolated stage removed"
    fi
  fi
}
trap rollback ERR

docker compose -p kipnerter-lfm3-rx480 -f "$MANIFEST" up -d --no-deps --no-build

# Real HTTP, real authenticated RX480 generation, fail-closed on status or reply.
python3 - <<'PY'
import json,re,time,sys,urllib.error,urllib.request
base="http://127.0.0.1:3355"
def request(url, data=None, timeout=8):
    req=urllib.request.Request(url,method="POST" if data is not None else "GET",
        data=data,headers={"Content-Type":"application/json"} if data is not None else {})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        return resp.status,resp.read(32769)
for n in range(40):
    try:
        status,html=request(base+"/")
        if status==200 and b"Message Kipnerter" in html: break
    except (OSError,ValueError): pass
    time.sleep(2)
else:
    print("FAIL: real Next.js stage never served chat UI"); sys.exit(1)
payload=lambda text:json.dumps({"messages":[{"role":"user","content":text}]}).encode()
try:
    request(base+"/api/chat/completions",payload("x"*2000))
except urllib.error.HTTPError as exc:
    if exc.code!=413:
        print("FAIL: invalid oversized input behavior"); sys.exit(1)
else:
    print("FAIL: oversize input accepted"); sys.exit(1)
try:
    status,bytes_=request(base+"/api/chat/completions",
        payload("What is 2 + 2? Reply with 4."),timeout=54)
    if len(bytes_)>32000: raise ValueError("oversized response")
    response=json.loads(bytes_)
    reply=response.get("reply")
    valid=(status==200 and response.get("model")=="LFM3-1.7B" and
        isinstance(reply,str) and bool(re.search(r"\b4\b",reply)) and
        "SIMULATED DEMO RESPONSE" not in reply and "LOCAL HTTP FIXTURE" not in reply)
    if not valid: raise ValueError("incorrect model or reply")
except Exception:
    print("FAIL: real authenticated RX480 model generation unavailable"); sys.exit(1)
print("RX480_REAL_STAGE_PASS: actual LFM3 answer through live Next.js loopback")
PY
trap - ERR
echo "STAGE_DEPLOYED: pinned real LFM3 gateway running localhost port 3355; public routes unchanged"
