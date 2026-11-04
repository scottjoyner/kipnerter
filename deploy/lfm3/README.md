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
