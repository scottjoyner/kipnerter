#!/usr/bin/env bash
# Opt-in local REAL LFM3-1.7B demo. Never affects public Caddy, iOS or fleet.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/apps/web"
MODEL_PORT="${KIPNERTER_LFM3_LOCAL_MODEL_PORT:-18777}"
CHAT_PORT="${KIPNERTER_LFM3_LOCAL_CHAT_PORT:-3362}"
GPU_LAYERS="${KIPNERTER_LFM3_LOCAL_GPU_LAYERS:-0}"
MODEL_ID=lfm3-1.7b-local
MODEL_REPO="LiquidAI/LFM3-1.7B-GGUF:Q4_K_M"
for command in node npm python3 curl; do
  command -v "$command" >/dev/null 2>&1 ||
    { echo "Required program missing: $command" >&2; exit 2; }
done
# Official llama.cpp installs may expose either the standalone server binary
# or the unified 'llama serve' frontend. Require one, never auto-install.
if command -v llama-server >/dev/null 2>&1; then
  LLAMA_SERVER=(llama-server)
elif command -v llama >/dev/null 2>&1; then
  LLAMA_SERVER=(llama serve)
else
  echo "llama.cpp server not found: install llama.cpp v0.8.0+ (llama-server or llama serve)." >&2
  exit 2
fi
if ! [[ "$GPU_LAYERS" =~ ^[0-9]{1,3}$ ]]; then
  echo "GPU layer count must be a non-negative integer." >&2; exit 2
fi
node -e 'if (+process.versions.node.split(".")[0] < 22) process.exit(1)' ||
  { echo "Node.js 22+ is required by this Next.js app." >&2; exit 2; }
python3 - "$MODEL_PORT" "$CHAT_PORT" <<'PY'
import socket,sys
ports=[]
for raw in sys.argv[1:]:
    if not raw.isdecimal() or not (1024 <= int(raw) <= 65535):
        raise SystemExit("Port must be an unprivileged numeric TCP port")
    port=int(raw)
    if port in ports: raise SystemExit("Model and web ports must differ")
    ports.append(port)
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: sock.bind(("127.0.0.1", port))
        except OSError: raise SystemExit(f"Local TCP {port} already in use; refusing to replace it")
PY
echo "REAL LOCAL LFM3-1.7B (official Liquid AI Q4_K_M GGUF) — not fleet or production"
echo "CPU-only default; optional GPU layers via KIPNERTER_LFM3_LOCAL_GPU_LAYERS."
echo "First run may download approximately 1.1 GB of model weights from Hugging Face."
echo "Review the model's lfm1.0 license before use."

TMP="$(mktemp -d "${TMPDIR:-/tmp}/kipnerter-lfm3-live.XXXXXXXX")"
MODEL_PID=""
WEB_PID=""
cleanup() {
  if [[ -n "$WEB_PID" ]]; then kill "$WEB_PID" 2>/dev/null || true; wait "$WEB_PID" 2>/dev/null || true; fi
  if [[ -n "$MODEL_PID" ]]; then kill "$MODEL_PID" 2>/dev/null || true; wait "$MODEL_PID" 2>/dev/null || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Build the exact current web checkout; never use a potentially stale .next.
(cd "$WEB" && npm ci --no-audit --no-fund && npm run build)

# Never change models/services already running on the machine. This isolated
# llama-server instance is created for this demo and owns only its own PID.
"${LLAMA_SERVER[@]}" -hf "$MODEL_REPO" --alias "$MODEL_ID" \
  --host 127.0.0.1 --port "$MODEL_PORT" --ctx-size 2048 \
  --parallel 1 --threads 4 --n-gpu-layers "$GPU_LAYERS" \
  >"$TMP/model.log" 2>&1 &
MODEL_PID=$!
ready=0
for attempt in $(seq 1 240); do
  if ! kill -0 "$MODEL_PID" 2>/dev/null; then
    echo "llama-server exited. Check llama.cpp version (v0.8.0+ required)." >&2
    tail -n 22 "$TMP/model.log" >&2
    exit 1
  fi
  if curl --silent --show-error --fail --max-time 2 \
    "http://127.0.0.1:$MODEL_PORT/v1/models" >"$TMP/models.json" 2>/dev/null; then
    if python3 - "$TMP/models.json" "$MODEL_ID" <<'PY'
import json,sys
try:
    body=json.load(open(sys.argv[1]))
    assert any(x.get("id")==sys.argv[2] for x in body.get("data",[]))
except (ValueError, OSError, AssertionError, AttributeError, TypeError):
    raise SystemExit(1)
PY
    then ready=1; break; fi
  fi
  if (( attempt % 30 == 0 )); then echo "Local model initializing; checking readiness..."; fi
  sleep 2
done
if [[ "$ready" != 1 ]]; then
  echo "Real local model failed readiness; no public changes made." >&2
  tail -n 22 "$TMP/model.log" >&2
  exit 1
fi

ENDPOINTS="$(python3 - "$MODEL_PORT" <<'PY'
import json,sys
print(json.dumps([dict(
  name="local_lfm3_demo",baseUrl="http://127.0.0.1:"+sys.argv[1],
  model="lfm3-1.7b-local",adapter="openai",role="interactive",
  maxInflight=1,maxOutputTokens=256
)],separators=(",",":")))
PY
)"
(
  cd "$WEB"
  exec env KIPNERTER_ENV=staging \
    NEXTAUTH_URL="http://127.0.0.1:$CHAT_PORT" \
    KIPNERTER_LFM3_ENDPOINTS="$ENDPOINTS" \
    node node_modules/next/dist/bin/next start -H 127.0.0.1 -p "$CHAT_PORT"
) >"$TMP/web.log" 2>&1 &
WEB_PID=$!
ready=0
for attempt in $(seq 1 45); do
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    echo "Local Next.js exited." >&2; tail -n 22 "$TMP/web.log" >&2; exit 1
  fi
  if curl --silent --fail --max-time 3 "http://127.0.0.1:$CHAT_PORT/chat" \
      >"$TMP/chat.html" 2>/dev/null; then
    if grep -q "Message Kipnerter" "$TMP/chat.html"; then ready=1; break; fi
  fi
  sleep 1
done
[[ "$ready" == 1 ]] || { echo "Web localhost demo not ready" >&2; tail -n 22 "$TMP/web.log" >&2; exit 1; }
python3 - "$CHAT_PORT" <<'PY'
import json,sys,urllib.request
base="http://127.0.0.1:"+sys.argv[1]
for route in ("/","/chat"):
    with urllib.request.urlopen(base+route,timeout=8) as response:
        body=response.read(250000)
        assert response.status==200 and b"Message Kipnerter" in body and b"LFM3-1.7B" in body
request=urllib.request.Request(
    base+"/api/chat/completions",
    data=json.dumps({"messages":[{"role":"user","content":"What is 2 + 2? Reply with the digit 4."}]}).encode(),
    method="POST",headers={"Content-Type":"application/json"})
with urllib.request.urlopen(request,timeout=55) as response:
    data=json.load(response)
    assert response.status==200 and data.get("model")=="LFM3-1.7B"
    reply=data.get("reply")
    assert isinstance(reply,str) and reply.strip()
    import re
    assert re.search(r"\b4\b", reply), "Actual local model returned an incorrect arithmetic canary."
    assert "SIMULATED DEMO RESPONSE" not in reply
    print("PASS: REAL local LFM3 generation via actual Next.js /api/chat/completions")
    print("Model response:",reply[:300])
PY
echo "LIVE LOCAL LFM3 CHAT: http://127.0.0.1:$CHAT_PORT/chat"
echo "This is the real model, not a simulation. Public kipnerter.com and iOS remain unchanged."
echo "Press Ctrl-C to stop only the demo's own web and llama-server processes."
while kill -0 "$WEB_PID" 2>/dev/null && kill -0 "$MODEL_PID" 2>/dev/null; do sleep 2; done
echo "A demo service exited; inspect the local test log and retry." >&2
exit 1
