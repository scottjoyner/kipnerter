#!/usr/bin/env bash
# Manually authorized REAL CPU staging only. Never uses RX480 keys or public ingress.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$ROOT/deploy/lfm3/compose.staging.cpu.yml"
PROJECT="kipnerter-lfm3-cpu"
[[ "${KIPNERTER_LFM3_CPU_STAGE_APPROVED:-}" == "YES" ]] || {
  echo "CPU_STAGE_HOLD: explicit isolated CPU staging approval missing" >&2; exit 3;
}
[[ "$(id -un)" == "kipnerter" ]] || { echo "CPU_STAGE_HOLD: wrong principal" >&2; exit 3; }
for key in KIPNERTER_LFM3_CPU_MODEL_IMAGE KIPNERTER_LFM3_CPU_WEB_IMAGE; do
  image="${!key:-}"
  [[ "$image" =~ ^[a-zA-Z0-9./_-]+(@sha256:[a-f0-9]{64})$ ]] || {
    echo "CPU_STAGE_HOLD: $key must be image@sha256:immutable-digest" >&2; exit 3;
  }
  docker image inspect "$image" >/dev/null 2>&1 || {
    echo "CPU_STAGE_HOLD: approved pinned image not present locally" >&2; exit 3;
  }
done
[[ -n "${KIPNERTER_LFM3_CPU_MODEL_FILE:-}" ]] || { echo "CPU_STAGE_HOLD: model path unset" >&2; exit 3; }
python3 - "$KIPNERTER_LFM3_CPU_MODEL_FILE" <<'PY'
import os,stat,sys
p=sys.argv[1]
try:
    s=os.lstat(p)
    valid=(os.path.isabs(p) and stat.S_ISREG(s.st_mode)
           and not stat.S_ISLNK(s.st_mode) and (s.st_mode & stat.S_IROTH)
           and s.st_size == 1099627808)
except OSError: valid=False
if not valid:
    print("CPU_STAGE_HOLD: official GGUF must be a world-readable regular file of verified size",file=sys.stderr)
    sys.exit(3)
PY
echo '3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4  '"$KIPNERTER_LFM3_CPU_MODEL_FILE" | sha256sum --check --status || {
  echo "CPU_STAGE_HOLD: official LiquidAI GGUF sha256 mismatch" >&2; exit 3;
}
bash "$ROOT/scripts/lfm3_cpu_stage_preflight.sh"
docker compose -p "$PROJECT" -f "$COMPOSE" config --quiet

# Do not remove unrelated services on rollback. Match exact instance and project.
cleanup_own_stage() {
  local name id project
  for name in kipnerter-lfm3-stage-cpu-web kipnerter-lfm3-stage-cpu-model; do
    id="$(docker inspect --format '{{.Id}}' "$name" 2>/dev/null || true)"
    [[ "$id" =~ ^[a-f0-9]{64}$ ]] || continue
    project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$id" 2>/dev/null || true)"
    if [[ "$project" == "$PROJECT" ]]; then
      docker rm -f "$id" >/dev/null 2>&1 || true
    fi
  done
}
trap cleanup_own_stage ERR

docker compose -p "$PROJECT" -f "$COMPOSE" up -d --no-build --pull never

# Require a real model-produced answer through the real Next.js gateway.
python3 - <<'PY'
import json,re,time,sys,urllib.error,urllib.request
base="http://127.0.0.1:3363"
def get(path,timeout=5):
    with urllib.request.urlopen(base+path,timeout=timeout) as r:
        return r.status,r.read(200000)
for attempt in range(90):
    try:
        status,html=get("/chat")
        if status==200 and b"Message Kipnerter" in html: break
    except (OSError,ValueError): pass
    time.sleep(2)
else:
    print("CPU_STAGE_FAIL: chat UI not ready",file=sys.stderr); sys.exit(1)
payload=json.dumps({"messages":[{"role":"user","content":"What is 2 + 2? Answer 4."}]}).encode()
req=urllib.request.Request(base+"/api/chat/completions",payload,
  {"Content-Type":"application/json"},method="POST")
try:
    with urllib.request.urlopen(req,timeout=65) as response:
        doc=json.load(response)
        valid=(response.status==200 and doc.get("model")=="LFM3-1.7B"
               and isinstance(doc.get("reply"),str)
               and bool(re.search(r"\b4\b",doc["reply"]))
               and "SIMULATED DEMO RESPONSE" not in doc["reply"])
except (OSError,ValueError,TypeError): valid=False
if not valid:
    print("CPU_STAGE_FAIL: real CPU model generation not proven",file=sys.stderr); sys.exit(1)
print("CPU_STAGE_REAL_PASS: actual official LFM3 model via Next.js localhost:3363")
PY
trap - ERR
echo "CPU_STAGE_ACTIVE: isolated localhost-only CPU candidate; public RX480/iOS routes unchanged"
