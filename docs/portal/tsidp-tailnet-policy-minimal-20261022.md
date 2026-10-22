# tsidp private Tailnet authorization — narrowly scoped repository candidate

**October 22, 2026.** This file documents a **repository sample policy**, not
an observation of the currently active Tailnet policy or permission to change
it. Source issue: [#79](https://github.com/scottjoyner/kipnerter/issues/79).

## What is required

The isolated `kipnerter-oidc-bootstrap-idp` container advertises
`TS_ADVERTISE_TAGS=tag:tsidp` and keeps `TSIDP_ENABLE_STS=0`.

The repository candidate `infra/tailscale/policy.hujson` now declares:

```json
"tagOwners": {
  "tag:tsidp": ["autogroup:admin"]
}
```

In its **existing** `grants` array it adds **only** an application capability:

```json
{
  "src": ["autogroup:admin"],
  "dst": ["tag:tsidp"],
  "app": {
    "tailscale.com/cap/tsidp": [{ "allow_admin_ui": true }]
  }
}
```

These two snippets are **additive fragments**, not a valid stand-alone full
Tailnet policy. Preserve the live policy's `ssh`, existing `tagOwners`,
`grants`, and any existing groups, hosts, posture and approval rules. Do not
copy this repository's entire `infra/tailscale/policy.hujson` into the admin
console; the live policy has additional legitimate roles and may have changed
since the last review. In particular, avoid creating a second `tagOwners` or
`grants` key, which could break or silently replace permissions. Save only
after an independent administrator reviews the smallest diff and the Tailscale
console validates the resulting *whole* policy.

**This admin-only capability does not enroll the device.** Enrollment requires
an authorized tag-owning account to approve the fresh interactive Tailscale
machine login for `kipnerter-idp-staging`. The admin UI capability is a
separate authorization required for restricted client registration later.
The capability deliberately omits `users`, `resources`, `ip`, `extraClaims`,
and `includeInUserInfo`; no STS authority is requested. Keep Funnel off for
the IdP and retain private Tailnet-only access.

## Important live policy risk

The operator shared a policy containing `src:["*"], dst:["*"], ip:["*"]` and
Funnel on `autogroup:member`. Neither is required for tsidp. They increase
access exposure and warrant a separately reviewed migration with live traffic
and SSH-policy tests **before** any removal or replacement. Do not change
these existing grants or disable fleet communications under this patch.

## Verification and acceptance

Run the **offline repo-sample preflight** before proposing the merge:

```sh
python3 -m scripts.portal_tsidp_policy_candidate_check
python3 -m pytest -q scripts/tests/test_portal_tsidp_policy_candidate_check.py
```

The checker parses only the repository's restricted JSON-with-line-comments
format. It checks one exact `tag:tsidp` administrator tag owner, one narrowly
scoped app grant, absence of wildcard network access in the *candidate*, and
an STS-disabled Compose. It never reads the live Tailscale policy, talks to an
IdP, modifies Docker, accepts browser auth or authorizes deployment. It always
reports `live_tailnet_policy_verified=false` and `release_gate=NO_GO`.

After live admin review and policy validation, an authorized Tailnet admin
must separately: approve the **current private** machine enrollment challenge;
verify tagged online node and MagicDNS; enable HTTPS; check strict discovery
issuer and endpoint locations; register the exact callback
`https://x1-370.tailcb8954.ts.net:8449/api/auth/callback/tailscale` through
the private IdP admin UI; place client/session secrets and subject/email
allowlists in approved secret custody; and perform **real browser** positive,
negative, expiry and revocation acceptance. An enrollment prompt, synthetic
JWT smoke test or successful policy syntax check is not authentication proof.
Production remains `NO_GO` independently of identity activation until
write-fenced PostgreSQL/MinIO recovery and independent custody pass.

Reference: [Tailscale tsidp](https://tailscale.com/docs/features/tsidp),
[policy file syntax](https://tailscale.com/docs/reference/syntax/policy-file),
[device tags](https://tailscale.com/docs/features/tags).

## Redacted physical enrollment diagnosis (no browser login URL in output)

Run the read-only operator check on `x1-370` whenever the staging IdP
appears stuck at a Tailscale login prompt:

```sh
python3 -m scripts.portal_tsidp_enrollment_diagnostic
python3 -m pytest -q scripts/tests/test_portal_tsidp_enrollment_diagnostic.py
```

The helper only reads Docker's exact container metadata and up to 80 log
lines **since its current start**. It verifies the pinned image, non-root
user, no exposed ports, read-only root filesystem, dropped capabilities,
restricted network/volume and resource limits. It emits **only structured
boolean and enum fields**, and never prints a login URL, access key,
container environment secret or raw error content. Docker writes tsidp
prompts to stderr, which is inspected safely in memory.

`AWAITING_INTERACTIVE_ADMIN_APPROVAL` means the current container has a
fresh interactive enrollment challenge, **not** that the live policy or
operator's tag ownership has been verified. `TAG_ASSIGNMENT_REJECTED`
indicates the tag owner or approving identity needs rechecking after the
failed browser attempt. `CONTAINER_STOPPED` or `UNKNOWN_HOLD` require a
separate operator investigation; the diagnostic never restarts containers.
A running IdP without a visible challenge is `ENROLLMENT_STATE_UNCONFIRMED`:
check its tagged Tailnet peer and HTTPS discovery before making claims.

**No diagnostic state is an authorization grant.** Only independently
approved browser login and negative acceptance tests can qualify private
OIDC access. `release_gate` is always `NO_GO` here, independently of
production recovery and data-custody requirements.

## Offline merge preview for the operator's existing Tailnet policy

The real Tailnet policy may differ significantly from the repository's
example. Never paste over it. If an authorized administrator has **exported**
the current policy to a local file on an approved host, they can review the
minimal fragments without making *any* policy changes:

```sh
python3 -m scripts.portal_tsidp_policy_merge_preview \
  --policy-file /path/to/privately-exported/current-tailnet-policy.hujson
python3 -m pytest -q scripts/tests/test_portal_tsidp_policy_merge_preview.py
```

The merge-preview tool reads the supplied file **once, locally**, parses
JSON with `//` line comments and trailing commas, rejects duplicate keys,
and emits only a minimal proposed `tagOwners` addition and/or exact admin-UI
app grant. It **does not output the full policy or any user identities**;
existing SSH/grant/Funnel rules remain untouched. If the tag already exists
with administrator ownership (as in the operator's last reported policy),
it proposes **only the admin-UI grant**. Custom tag owners, pre-existing
conflicting IdP capabilities, duplicate keys, malformed syntax or unsupported
HuJSON result in review/HOLD rather than a guessed patch. It reports warnings
if a blanket `src=* / dst=* / ip=*` grant or member-wide Funnel eligibility
is present; those risks require a **separate migration** with connectivity
impact analysis, not a silent automatic replacement.

This is **not** the official Tailscale policy parser or API validator: it
supports only a restricted HuJSON subset. A green merge preview means merely
that the local candidate has a non-destructive, tightly scoped proposed diff.
The authorized administrator must still validate the entire resulting
policy in the Tailscale admin console (or the official
`POST /api/v2/tailnet/{tailnet}/acl/validate` endpoint with properly scoped
credentials), review and apply it, then independently prove tag assignment.
No live credentials should be saved in the repository or pasted in logs.
`release_gate=NO_GO` always.
