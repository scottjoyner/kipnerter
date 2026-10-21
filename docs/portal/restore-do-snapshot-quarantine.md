# October 18 production snapshot: two-stage quarantined recovery plan

**State on October 20, 2026:** DigitalOcean snapshot `250354430`
(October 18 12:08:13 UTC, NYC3) is `type=snapshot`,
`status=available`. The original production Droplet `593032509`
(`kipnerter-prod-01`) remains running. No clone has been created.

**Production rollout and historic web/API rollback: HOLD.** Source bytes
matching Git `05955fe` are not executable OCI restoration, and a
provider-available snapshot does not establish consistent PostgreSQL
or MinIO recovery.

## Why the restore must be split

The connected DigitalOcean operations can create a Droplet with tags,
but cannot create/read a Cloud Firewall. Creating the production-derived
snapshot immediately would boot a new host which may contain private
SSH keys, Tailnet identity, tokens, databases and background jobs,
potentially with public networking. Do **not** create a new Droplet
until a separate security administrator has provisioned the quarantine
firewall and returned provider-confirmed readbacks.

DigitalOcean Cloud Firewalls combine allow rules across firewalls.
An empty-rule firewall is **not sufficient** if another firewall
accidentally also applies. Explicit deny rules override allows, even
across multiple firewalls. See:
https://docs.digitalocean.com/products/networking/firewalls/how-to/configure-rules/
and
https://docs.digitalocean.com/products/networking/firewalls/details/limits/

## Stage A: firewall and tag ONLY — no clone

`infra/digitalocean/terraform/recovery-quarantine/main.tf`
declares only one uniquely tagged Cloud Firewall and its unique tag.
It has **explicit inbound and outbound deny-all rules**:
`protocol=all`, `action=deny`, for both
`0.0.0.0/0` and `::/0`. These deny all IP protocols and ports,
including ingress and egress over the public and VPC networks.
It has `prevent_destroy=true`, no Droplet resource, no DNS changes,
no project changes and no production IDs or tags as targets.
Its target tag is exclusively
`kp-dr-quarantine-20261018-250354430`.

The repository's CI validates this module; there is **no Terraform
apply workflow**. An authorized operator must manage protected remote
state and apply this *quarantine-only* module in an approved, reviewed
change. Do not apply the existing production Terraform directory as
part of this operation.

After Stage A, obtain authoritative, fresh, full readbacks from the
provider for:

- Snapshot image ID `250354430` (available, correct creation date,
  NYC3, min disk size not exceeding 80 GiB).
- Firewall UUID, `status=succeeded`, exactly the unique quarantine
  tag, no preexisting Droplet IDs or pending changes, exactly one
  explicit IPv4+IPv6 all-protocol DENY rule inbound and outbound, and
  **no ALLOW rules**.
- Complete account Droplet inventory with tags. The active original
  production Droplet ID `593032509` and every other existing Droplet
  must **not** have the quarantine tag.

Securely save these as exact JSON responses, separately, locally.
Do not paste provider account tokens into GitHub or CI logs.

## Stage B: explicit owner approval; offline-only restore preflight

Use `scripts/portal_do_snapshot_quarantine.py` with owner-approved
input readback files. The program never calls the network or performs
any action. It checks metadata and returns a **candidate create
request**, not a created Droplet. The separate
`--owner-approval` phrase is an intent marker, not an authentication
secret or substitute for the owner's authenticated approval.

```bash
python3 scripts/portal_do_snapshot_quarantine.py \
  --image-readback /private/approved-snapshot.json \
  --firewall-readback /private/approved-quarantine-firewall.json \
  --droplets-readback /private/approved-droplets.json \
  --owner-approval AUTHORIZE_BILLABLE_ISOLATED_RESTORE_250354430
```

Only a clean `RECOVERY_FIREWALL_PREFLIGHT_OK_NO_CLONE_CREATED`
report may be used by a human operator to prepare a separate
DigitalOcean clone change. The returned request deliberately fixes
snapshot ID, region, size, no monitoring/backups, and **only** the
unique quarantine tag. Do not pass any other tag, join the production
VPC intentionally, attach existing production volumes, enable shared
Tailscale access, or alter the production host's DNS or address.

Before issuing an actual Droplet create, the operator must independently
revalidate provider firewall/tag attachment timing and audit the
combined effective rules. A provider API success at firewall creation
is **not physical proof** that the firewall was attached from the
clone's first packet. Document this residual uncertainty and require
security review. The quarantined clone has no expected SSH/network
path: access should use a provider-approved isolated console or an
offline forensic procedure only; do not loosen the firewall merely to
make interactive SSH convenient.

Creation of a new, running, 80-GiB-capable 2vCPU/4GiB Droplet incurs
charges and is **not authorized by this code or by converting the
backup into a retained snapshot**. The snapshot itself can also incur
continuing storage charges.

## Postboot forensic acceptance

From the completely quarantined derived host, before running the
application:

1. Keep jobs, webhooks, emails, backups, Nextcloud sync, Tailscale and
   service auto-start disabled. No connection to real API, Neo4j,
   MinIO, Postgres, AssistX, Sophia or the active droplet.
2. Record and privately verify the image cache for exact historical
   API `sha256:7efc68e54ff1289ee2033440ea0ee176962e3a57e0d24e091a2365ca769d5860`
   and web `sha256:5dfd3de1d45260b826d52eb107df8398e872121c9d98ade02540f3917fc78726`.
   Do not print `docker inspect` environment values or save layers
   publicly. Absence in **one** snapshot does not prove universal
   absence.
3. If both exact images exist, verify full OCI config/layer/diffID
   integrity with the existing offline verifier, then old route/auth
   parity and a **genuine** failed-upgrade revert.
4. Independently verify *actual* PostgreSQL and MinIO restore,
   replay/high-water freshness and source custody. A booted snapshot
   alone is not a database restore receipt.
5. Obtain OIDC physical/browser testing, independent review, and
   production operator authorization before ever changing
   `kipnerter.com/chat`.

## Controls

`python3 -m unittest scripts.tests.test_portal_do_snapshot_quarantine -v`
has synthetic allow/deny, wrong snapshot identity, wrong tag, pending
changes, malformed JSON, missing production Droplet, overlap with a
production tag and missing explicit approval controls. CI validates
the separate Terraform module, but does not `terraform apply` or
create a Droplet. **No stage modifies production.**
