# Dedicated LFM3 service manifests

These files mirror the rootless units installed and tested on the fleet on
November 4, 2026. Do not replace existing unit files blindly: compare their
current contents, exact host identity, backend build, and model paths first.

- The R9700 bridge exposes only its **pre-existing API-key-protected** local
  research listener over Tailscale. Stopping this bridge never stops that model.
- The RX 480 Vulkan server is independent, single-slot and admitted only when
  VRAM and host-memory preflights pass.
- OptiPlex is CPU-only, deliberately lower priority and memory/CPU bounded.
- Dedicated token files must be created through an authorized secret provisioning
  workflow, under the specified home directory at permission mode 0600.
  Never commit or print their contents.

For the two preflight scripts, install their contents at the matching paths
under `~/.local/libexec/kipnerter/` with mode 0750. Compare unit files against
the live `~/.config/systemd/user/` versions before any replacement. Run
`systemctl --user daemon-reload` only after operator review. Each unit is
independently enabled, inspected, and reversed with:

```sh
systemctl --user status kipnerter-lfm3-rx480.service
systemctl --user disable --now kipnerter-lfm3-rx480.service
```

Substitute the correct unit for the particular node; never kill generic
inference servers or modify x1-370. See
[`docs/operations/lfm3-fleet-admission.md`](../../docs/operations/lfm3-fleet-admission.md)
for verified health, per-node gateway config and remaining rollout gates.

## Private gateway acceptance and approved secret mounts

The **verified worker-local keys already exist** on R9700, RX 480, and
OptiPlex. The public web gateway remains unprovisioned. Do not copy those
keys with chat, shell command output, GitHub, iOS, or Docker environment
variables. An earlier credential-transfer operation was blocked and must
not be bypassed.

This directory includes two deploy-time aids that are safe to review and
test **without actual credentials**:

- `compose.staging.yml`: an *unapplied* template for a **second**
  localhost-only staging candidate (`127.0.0.1:3354`). Its three
  exact-model workers have separate credential **references**. It mounts
  an explicitly provisioned private directory at
  `/run/secrets/kipnerter-lfm3` as read-only and refuses to silently
  create a missing host directory. No public Caddy route is specified.
- `gateway-acceptance.mjs`: a fail-closed, one-generation acceptance
  gate. It checks the localhost home page, pre-inference HTTP 413 handling,
  and *only metadata* (regular file / mode / size) for each secret mount.
  It does **not** read or print token values. If any mount is missing,
  the result is `HOLD` and no inference is requested. After approved
  provisioning, it requires a real `LFM3-1.7B` HTTP 200 response with
  a nonempty correct arithmetic answer. An HTTP 503 or bad model is
  not considered release-ready.

A production-host **read-only Compose syntax check** passed with:
`KIPNERTER_LFM3_STAGE_IMAGE=kipnerter-lfm3-staging:1f2f788`,
`KIPNERTER_LFM3_SECRET_DIR=/nonexistent/lfm3-staging-secrets`, and
`docker compose -f - config --quiet`. This only parses the plan; no
container, directory, mount, or secret was created.

For a future approved operator change, first have the designated
secrets-management process provision the three root-owned 0400/0600
regular key files into a locked-down directory on the Docker host. Review
that private directory's ownership, deployment ACLs, canonical model
aliases, existing Caddy ingress and image SHA **before** issuing a new
staging `docker compose up` from an authorized checkout. Leave the
existing localhost candidate running until the new one passes the
gateway-acceptance check, and **do not expose either staging listener**.

The production droplet does not currently have a host-level `node`
command, but its web container includes Node.js. The acceptance module
can be run from an authorized Node environment with access to the
loopback stage URL and Docker metadata inspection, or invoked through
a reviewed container-local harness. The current staging check was
run without copying any key material and returned:

```json
{"decision":"HOLD","gate":"protected-model-secrets","workerMounts":{"r9700":"missing","rx480":"missing","optiplex":"missing"}}
```

**Release remains HOLD** until an approved secret mount, a real
authenticated request through the staged Next.js route, and independent
edge/global abuse-control verification all pass. Only then review public
Caddy promotion and the signed iOS/TestFlight gate. The iOS app uses
`https://kipnerter.com/api/chat/completions` and must never contain
Tailnet credentials or individual worker addresses.
