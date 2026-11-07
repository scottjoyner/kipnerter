import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const launcher = readFileSync(
  new URL("../../../scripts/lfm3_live_local_demo.sh", import.meta.url), "utf8");

test("real-model demo uses only official Liquid AI model and conservative local port binding", () => {
  assert.match(launcher, /LiquidAI\/LFM3-1\.7B-GGUF:Q4_K_M/);
  assert.match(launcher, /--alias "\$MODEL_ID"/);
  assert.match(launcher, /LLAMA_SERVER=\(llama-server\)/);
  assert.match(launcher, /LLAMA_SERVER=\(llama serve\)/);
  assert.match(launcher, /"\$\{LLAMA_SERVER\[@\]\}" -hf/);
  assert.match(launcher, /--host 127\.0\.0\.1 --port "\$MODEL_PORT"/);
  assert.match(launcher, /next start -H 127\.0\.0\.1 -p "\$CHAT_PORT"/);
  assert.match(launcher, /maxInflight=1,maxOutputTokens=256/);
  assert.match(launcher, /--n-gpu-layers "\$GPU_LAYERS"/);
  assert.match(launcher, /KIPNERTER_LFM3_LOCAL_GPU_LAYERS:-0/);
});
test("real-model script does not load any private fleet key or restart existing processes", () => {
  assert.doesNotMatch(launcher, /KIPNERTER_LFM3_TOKEN_|\/run\/secrets|tailnet|100\.78\.106\.121/);
  assert.doesNotMatch(launcher, /systemctl|docker compose down|pkill|killall|kill -9|Caddyfile/);
  assert.match(launcher, /kill "\$WEB_PID"/);
  assert.match(launcher, /kill "\$MODEL_PID"/);
  assert.match(launcher, /Local TCP \{port\} already in use/);
});
test("a real model completion, not a catalog or canned response, is required", () => {
  assert.match(launcher, /\/api\/chat\/completions/);
  assert.match(launcher, /data\.get\("model"\)=="LFM3-1\.7B"/);
  assert.match(launcher, /assert isinstance\(reply,str\) and reply\.strip\(\)/);
  assert.match(launcher, /assert "SIMULATED DEMO RESPONSE" not in reply/);
  assert.match(launcher, /re\.search/);
  assert.match(launcher, /incorrect arithmetic canary/);
  assert.match(launcher, /PASS: REAL local LFM3 generation/);
});
