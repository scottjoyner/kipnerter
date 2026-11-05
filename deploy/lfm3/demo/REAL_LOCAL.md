# Real LFM3-1.7B demo on a development laptop or desktop

This is an **actual Liquid AI LFM3-1.7B model**, not the simulated fixture
in `deploy/lfm3/demo/DOCKER.md`. It connects the current Kipnerter
Next.js `/` and `/chat` interface to an **independent local**
llama.cpp server, without Fleet Commander, the production DigitalOcean
droplet, a Tailnet secret, or a Caddy release.

Official model: https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF
Quantization: `LFM3-1.7B-Q4_K_M.gguf` (~1.1 GB model download).
The model's license is **lfm1.0**; review its terms before using.
The model card states llama.cpp **v0.8.0 or newer** is required.

## First-time prerequisites

You need Node.js 22+, npm, Python 3, curl, and an up-to-date
llama.cpp build with LFM3 support. Either `llama-server` **or**
the newer unified `llama serve` executable is supported. On macOS,
one installation method is `brew install llama.cpp` (update if outdated).
The first launch downloads the official GGUF from Hugging Face into the
llama.cpp cache. Disk, RAM, and network capacity must be available.
Do not use a random GGUF mirror or pass private model tokens to this demo.

## Start genuine local chat

From a trusted checkout of the feature PR:

```sh
git clone -b feat/lfm3-native-homechat-20261103 https://github.com/scottjoyner/kipnerter.git
cd kipnerter
bash scripts/lfm3_live_local_demo.sh
```

After the script reports an actual HTTP 200 model completion, visit
**http://127.0.0.1:3362/chat** in the same machine's browser.
The home route `/` is the same public chat UI and `/fleet` remains
an operator-only interface. Start with `2 + 2`, then another question.
The script first runs the full local Next.js build, launches its own
separate llama-server, checks the official model alias, and verifies a
**real nonempty Next.js → llama-server chat completion** before reporting
ready. Press Ctrl-C to stop only these two new processes.

Defaults are deliberately conservative: CPU-only, 4 threads, 2,048-token
context, one concurrent request, a 256-token output cap and no public
listener. If the machine has adequate GPU memory and supported llama.cpp
acceleration, you can opt in to GPU layers:

```sh
KIPNERTER_LFM3_LOCAL_GPU_LAYERS=99 bash scripts/lfm3_live_local_demo.sh
```

The dedicated localhost ports are configurable with
`KIPNERTER_LFM3_LOCAL_MODEL_PORT` (default 18777) and
`KIPNERTER_LFM3_LOCAL_CHAT_PORT` (default 3362). Occupied ports fail
closed; the script never stops or replaces a previously running service.
Both listeners bind exclusively to `127.0.0.1`. It does not expose
private SensorGraft data, tools, model workers or credentials.

## Boundaries

Unlike the simulated CI demo, this setup requires a **real** downloaded
model and local supported hardware. GitHub CI can validate its syntax
and source safety policy, **not** prove that every user's CPU/GPU and
llama.cpp version will run it. The on-machine real generation test is the
acceptance gate. This is *not* evidence that public kipnerter.com or
the pinned iOS HTTPS endpoint is deployed. Production and TestFlight
remain HOLD pending the separate authenticated fleet staging and
edge-security release checks.
