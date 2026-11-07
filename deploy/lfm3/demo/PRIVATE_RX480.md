# One-worker private LFM3 demo — does not authorize production

This is a **real-model** route for an operator to test one already-admitted
RX 480 LFM3 worker via the actual Next.js chat gateway, without waiting for
credentials for all three workers. It is *not* a release gate for
`kipnerter.com`, the full three-node fleet, or iOS TestFlight.

The stage is exclusively host loopback `127.0.0.1:3356`, not public
Caddy, TLS ingress, DNS or a Tailnet listener. To reach it from a trusted
workstation, use an authenticated SSH local-port forward to the production
host *after* the authorized owner enables it; never publish port 3356.

## Prerequisites and safe order

1. Verify the release PR exact head and green CI; build/review a pinned staging
   image from that commit on a trusted builder. Do not silently reuse an older
   production image. Record the immutable image digest and rollback path.
2. An approved secrets-management workflow, **not a chat command or GitHub
   workflow**, must provision the RX 480 bearer token into a root-owned,
   non-symlink, restrictive regular file `rx480.key` (0400/0600, 16–2048 B)
   beneath a locked-down directory on the stage host. Do not print or copy its
   value into logs, environment variables, GitHub, a browser, or an iPhone.
   The target must be readable by the reviewed container identity.
3. Have the operator review `compose.demo-rx480.yml`, the mounted directory,
   exact Docker image digest, connection to the existing `kipnerter_frontend`
   network, and the RX 480 Tailnet ACL. This container must only reach
   `100.78.106.121:19176`; never alter an existing inference process.
4. Preflight `docker compose -f deploy/lfm3/compose.demo-rx480.yml config --quiet`
   with approved environment references. `create_host_path: false` ensures
   a missing credential directory is not silently created.
5. After authorized staging activation only, verify metadata and real generation
   using `node deploy/lfm3/private-demo-acceptance.mjs` *on the stage host*.
   It reports `HOLD` if metadata or the worker secret is unavailable,
   `FAIL` on wrong model/invalid output and `DEMO_PASS` only for a verified
   same-model response through the loopback Next.js endpoint.
6. Use an authorized SSH port forward to open
   `http://127.0.0.1:3356/chat` in a trusted browser, exercise normal
   chat and error states, then remove only the **demo** container after testing.
   Keep existing Caddy routing, web production container, and model workers
   untouched.

The acceptance script inspects only the **file type, mode, size and explicit
one-node roster** from inside the stage container; it never reads or prints
the credential. The worker key must be provisioned separately by approved
means. The script does not claim independent host image custody or user
identity; it is bounded operational smoke evidence, not a security audit.

**Explicit production HOLD:** The full `gateway-acceptance.mjs` still
requires all approved worker secret mounts and real staging generation.
Shared ingress abuse controls, deployment authorization, privacy, rollback,
public HTTPS acceptance, and device/TestFlight release gates remain separate.
