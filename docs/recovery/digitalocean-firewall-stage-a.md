# October 18 snapshot: separate, owner-gated Cloud Firewall Stage A

**Recovery remains HOLD.** The October 18 DigitalOcean snapshot
`250354430` is retained/available, but its original web/API OCI images,
PostgreSQL state and MinIO objects have **not** been restored or verified.

## Why this is a separate PR from #18

PR #18 is the unfinished 1.7 production portal release, so it should not
be merged merely to access the recovery firewall configuration. The
small, independently reviewed Stage A workflow can be merged to `master`
without deploying web/API code. It never creates a Droplet.

Existing connected DigitalOcean actions cannot configure firewalls, and
x1-370 has no DigitalOcean API token in its current shell. This workflow
uses the already configured, **protected GitHub production environment**
secret `DIGITALOCEAN_ACCESS_TOKEN`, only on a manually dispatched
`master` job. GitHub environment rules and owner authorization remain
required; the static confirmation phrase is **not** an authentication
credential. No automatic triggers exist.

## Stage A operations: list / read / optionally create quarantine only

Workflow file: `.github/workflows/recovery-firewall-stage-a.yml`.
Backend: `scripts/do_recovery_quarantine_firewall.py`.

**Default mode: inventory.** Only reads:
- Snapshot ID `250354430`, type snapshot, status available, exact
  October 18 creation date and `nyc3` region.
- All Droplets, fully paginated, including active production
  `kipnerter-prod-01` ID `593032509`.
- Current tag resources and all existing firewall rules.

If a candidate firewall already exists, it must **exactly** match the
immutable quarantine name/tag, include no Droplet IDs or pending changes,
be in succeeded state, and have six IPv4/IPv6 **explicit DENY** rules:
TCP 1-65535, UDP 1-65535, and ICMP, each inbound and outbound, and no
extra allow rules. If any mismatch appears, the workflow fails HOLD
without attempting changes.

**Mode: apply-firewall.** Only runs after someone with the appropriate
GitHub environment authorization dispatches the workflow on `master`
with exact confirmation:

`APPLY_FIREWALL_ONLY_250354430_NO_DROPLET`

It first performs the same full read-only checks and refuses to run if
production or any other Droplet carries the quarantine tag. Only then
it may `POST /v2/tags` for the unique tag and
`POST /v2/firewalls` for the exact six DENY rules. Each mutation is
idempotent or fails closed if existing resources have inconsistent
identity. It reads back all effective firewall rules, checks the tag
has **zero** linked Droplets, and never sends requests to:
`/v2/droplets` (except GET inventory), backups, snapshots, DNS,
production containers, disks, or application services. No secrets or
full provider responses are written into logs.

Cloud Firewalls are provided by DigitalOcean at no additional cost,
but a later restored **Droplet** and the retained snapshot may incur
charges. This workflow does **not** authorize that later restore.

### Manual owner UI steps

1. Review and merge the narrow Stage A PR into `master` independently
   from the unfinished portal release. Verify its hosted test checks.
2. Open GitHub → `scottjoyner/kipnerter` → **Actions** →
   `recovery-firewall-stage-a` → **Run workflow**.
3. Select branch `master`, mode `inventory` and leave confirmation
   blank. Complete any protected `production` environment review.
   Expect `FIREWALL_NOT_INSTALLED` (not a failure) until applied.
4. For a separate approved Stage A action, choose `apply-firewall`
   and supply the exact confirmation phrase above. The job must report
   `FIREWALL_INSTALLED_VERIFIED` or
   `FIREWALL_ALREADY_VERIFIED`. On any HOLD, investigate privately.
5. Re-run `inventory` after the mutation to verify a settled, exact
   deny-only firewall and no Droplet attachment.

The provider token must support scoped `image:read`, `droplet:read`,
`tag:read`, `tag:create`, `firewall:read`, and `firewall:create`.
No token values should be copied into chats, files, PRs, or artifacts.
This workflow cannot apply a user-supplied Terraform state file and
never calls `terraform apply`.

### Remaining restore gate (separate approval required)

The separate offline restore preflight on [PR #18](https://github.com/scottjoyner/kipnerter/pull/18)
is **not yet satisfied merely by creating the firewall**. After Stage A
readback, the owner/security reviewer must independently establish
network confinement **from a cloned server's first packet**; attaching
a tag to a newly created Droplet is not in itself physical evidence of
instantaneous enforcement. The cloned guest would contain
production-derived identities and secrets.

Only after verifying that boundary, obtaining explicit approval for
another billable Droplet, and selecting a safe offline access method
may an actual isolated snapshot clone be created. A booted clone is
still not a verified PostgreSQL/MinIO restore, original OCI image
recovery, rollback or production cutover approval.

**This Stage A module leaves production, public DNS, the snapshot,
data stores, live containers, and ingress unchanged.**
