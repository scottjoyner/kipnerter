#!/usr/bin/env bash
# First-party REAL local CPU GGUF + Next.js stage, no public routes.
set -euo pipefail
[[ "$(id -un)" == kipnerter && $# -eq 4 ]] || { echo "HOLD: invalid stage invocation"; exit 3; }
SHA="$1"; WEB_ID="$2"; MODEL_ID="$3"; RUN="$4"
[[ "$SHA" =~ ^[a-f0-9]{40}$ &&
   "$WEB_ID" =~ ^sha256:[a-f0-9]{64}$ &&
   "$MODEL_ID" =~ ^sha256:[a-f0-9]{64}$ &&
   "$RUN" =~ ^[0-9]{8,14}$ ]] || { echo "HOLD: invalid image/source identities"; exit 3; }
DIR="/home/kipnerter/.local/state/kipnerter-lfm3/local-cpu/$SHA-$RUN"
MANIFEST="$DIR/compose.local-cpu-real-v2.yml"
MODEL_FILE="$DIR/models/LFM3-1.7B-Q4_K_M.gguf"
WEB_IMAGE="kipnerter-lfm3-local-web:$SHA"
MODEL_IMAGE="kipnerter-lfm3-local-server:$SHA"
EXPECTED_WEIGHT="3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4"
[[ -f "$MANIFEST" && ! -L "$MANIFEST" &&
   -f "$MODEL_FILE" && ! -L "$MODEL_FILE" ]] || { echo "HOLD: stage inputs missing"; exit 3; }
realweb="$(docker image inspect --format '{{.Id}}' "$WEB_IMAGE" 2>/dev/null || true)"
realmodel="$(docker image inspect --format '{{.Id}}' "$MODEL_IMAGE" 2>/dev/null || true)"
[[ "$realweb" == "$WEB_ID" && "$realmodel" == "$MODEL_ID" ]] ||
  { echo "HOLD: stage image identities disagree with source runner"; exit 3; }
size="$(stat -c %s "$MODEL_FILE")"
sum="$(sha256sum "$MODEL_FILE" | awk '{print $1}')"
[[ "$size" == 1099627808 && "$sum" == "$EXPECTED_WEIGHT" ]] ||
  { echo "HOLD: official LFM3 Q4_K_M model hash/size mismatch"; exit 3; }
available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
[[ "$available" =~ ^[0-9]+$ ]] || exit 3
(( available >= 2200000 )) ||
  { echo "HOLD: too little available production RAM for CPU stage"; exit 3; }
for name in kipnerter-lfm3-local-cpu kipnerter-lfm3-local-web; do
  docker container inspect "$name" >/dev/null 2>&1 &&
    { echo "HOLD: existing staged container not replaced"; exit 3; }
done
export KIPNERTER_LFM3_CPU_SERVER_IMAGE="$MODEL_IMAGE"
export KIPNERTER_LFM3_LOCAL_WEB_IMAGE="$WEB_IMAGE"
export KIPNERTER_LFM3_LOCAL_MODEL_DIR="$DIR/models"
docker compose -p kipnerter-lfm3-local-real -f "$MANIFEST" config --quiet
# Never touch containers outside this isolated named Compose project.
rollback() {
  for name in kipnerter-lfm3-local-web kipnerter-lfm3-local-cpu; do
    status="$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || true)"
    oom="$(docker inspect --format '{{.State.OOMKilled}}' "$name" 2>/dev/null || true)"
    exit_code="$(docker inspect --format '{{.State.ExitCode}}' "$name" 2>/dev/null || true)"
    echo "stage_container=$name status=$status oom=$oom exit_code=$exit_code"
    id="$(docker inspect --format '{{.Id}}' "$name" 2>/dev/null || true)"
    [[ "$id" =~ ^[a-f0-9]{64}$ ]] || continue
    project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$id" 2>/dev/null || true)"
    image="$(docker inspect --format '{{.Image}}' "$id" 2>/dev/null || true)"
    if [[ "$project" == kipnerter-lfm3-local-real &&
          ( "$image" == "$WEB_ID" || "$image" == "$MODEL_ID" ) ]]; then
      docker rm -f "$id" >/dev/null 2>&1 || true
      echo "ROLLBACK: removed only failed real CPU-stage container"
    fi
  done
}
trap rollback ERR
docker compose -p kipnerter-lfm3-local-real -f "$MANIFEST" up -d --no-build --no-deps
python3 - <<'PY'
import json,re,sys,time,urllib.error,urllib.request
base="http://127.0.0.1:3356"
def query(url, data=None, timeout=8):
    req=urllib.request.Request(url,method="POST" if data is not None else "GET",
        data=data,headers={"Content-Type":"application/json"} if data is not None else {})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        return response.status,response.read(32769)
for n in range(60):
    try:
        code,page=query(base+"/")
        if code==200 and b"Message Kipnerter" in page:break
    except (OSError,ValueError):pass
    time.sleep(2)
else:
    print("FAIL: localhost real Next.js chat page unavailable");sys.exit(1)
message=lambda v:json.dumps({"messages":[{"role":"user","content":v}]}).encode()
try:
    query(base+"/api/chat/completions",message("x"*2000))
except urllib.error.HTTPError as exc:
    if exc.code!=413:
        print("FAIL: input-limit gate is not enforced");sys.exit(1)
else:
    print("FAIL: oversized prompt was accepted");sys.exit(1)
for n in range(4):
    try:
        code,raw=query(base+"/api/chat/completions",
           message("What is 2 + 2? Reply only with the digit 4."),timeout=54)
        if len(raw)>32000: raise ValueError("oversized model response")
        ans=json.loads(raw)
        reply=ans.get("reply")
        if (code!=200 or ans.get("model")!="LFM3-1.7B"
           or not isinstance(reply,str) or not re.search(r"\b4\b",reply)
           or "SIMULATED DEMO RESPONSE" in reply
           or "LOCAL HTTP FIXTURE" in reply):
            raise ValueError("model identity/reply mismatch")
        print("LOCAL_CPU_REAL_STAGE_PASS: genuine official GGUF LFM3 -> Next.js -> localhost")
        break
    except urllib.error.HTTPError as exc:
        if exc.code not in (429,503) or n==3:
            print("FAIL: model HTTP error not accepted");sys.exit(1)
        time.sleep(8)
    except Exception:
        print("FAIL: real local model generation did not pass");sys.exit(1)
else:
    print("FAIL: model stayed unavailable");sys.exit(1)
PY
trap - ERR
echo "LOCAL_CPU_STAGE_DEPLOYED: real LFM3 localhost 3356, strict memory caps, public ingress unchanged"
