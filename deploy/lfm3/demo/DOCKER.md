# One-command local Kipnerter LFM3 chat demo (simulated only)

This starts the **actual Next.js Kipnerter home/chat implementation**, with a
**deterministic simulated LFM3 endpoint** on a private Docker-only network.
It is intended for visual and browser workflow testing; the fixture has no
LFM3 weights, intelligence, production keys, remote workers, or agent tools.
Every reply is clearly labeled `SIMULATED DEMO RESPONSE`.

Requires Docker with Compose v2, and Git. From the repo root:

```sh
docker compose -f deploy/lfm3/demo/compose.simulated.yml up -d --build
bash deploy/lfm3/demo/smoke_docker.sh
```

Open **http://127.0.0.1:3360/chat** or **http://127.0.0.1:3360/** in a
browser on that same computer. The protected operator UI remains at `/fleet`.
Send a message and confirm the simulated response; try New Chat and a long
message for input-limit behavior. The fixture deliberately echoes a bounded
preview of normal prompts, but never executes commands.

To stop and clean up:

```sh
docker compose -f deploy/lfm3/demo/compose.simulated.yml down --remove-orphans
```

The web port is bound to `127.0.0.1` only. The model fixture has **no
host-published port**, and only the fixture/model Docker network is marked `internal` (the
web's separate preview bridge is required for host loopback access). No
production public route, DNS, Caddy, inference node, secret mount, telemetry
database, or iOS TestFlight is modified. The Docker Python base image should
be reviewed under local image provenance policies if running on a sensitive
host; it is a development-only image, not the production Nginx candidate.
To avoid a local port collision, set `KIPNERTER_LFM3_DEMO_PORT=3361` (or
another loopback port) for both `up` and `smoke_docker.sh`.

For real LFM3 generation, use the separate reviewed single-worker private
staging plan in `PRIVATE_RX480.md`. A simulated success is **not** an
authentication or public-release gate.
