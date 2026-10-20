# Staging readiness trust boundary — default branch only

The web portal needs a real Tailscale `tsidp` identity service and an
administratively approved staging host before a signed browser login can be
accepted. This readiness workflow performs **NO writes or deployment**.

A previous draft workflow accepted arbitrary `workflow_dispatch`
`planned_portal_sha`, checked out and executed source files from that SHA,
and supplied staging credentials as job-level environment variables. A
repository-owner dispatch alone does not make arbitrary checkout content a
safe recipient of private secrets. Its security depended on how GitHub
Actions resolved and protected the source and run context.

The guarded version copies the already reviewed, fixed-SHA default-branch
workflow and **requires dispatch on `refs/heads/master`**. It:
- Pins the exact candidate SHA in code, with no user-supplied checkout ref.
- Fetches the candidate without persisting repository credentials.
- Checks the complete SHA and the ten approved script, Compose, NextAuth and
  identity-test blob identities **before** supplying any staging secrets.
- Runs deny-only unit tests and Docker Compose `config`, not `up`.
- Introduces private credentials only inside the steps that need them, and
  never echoes their values into logs or creates an artifact.
- Uses a read-only Tailscale peer selection and `tailscale ping`, never SSH,
  traffic routing, service restart, model dispatch, or production storage.
- Keeps real OIDC browser acceptance, independent restore and public cutover
  explicitly **NOT VERIFIED** even after a configuration PASS.

The initial immutable pin still references reviewed
`999f3caa49da73b89b5534c2f9037a78bc799797`. It does **NOT**
qualify any newer private-preview or PR #61 combined build. When the
reviewed combined portal release is approved for integration, change the
pin and re-review the source hashes through a separate protected PR.
Do not update the pin to an unreviewed branch or use a runtime input.

The workflow must only run after a tailnet administrator configures the
`tsidp` server with stable key custody, a restricted capability grant, a
registered client with the exact
`https://staging.kipnerter.com/api/auth/callback/tailscale` callback, and
the staging-tagged host and HTTPS route. Store all credentials in the
protected GitHub staging environment, not in PR comments.

The six static regression tests in
`tests/test_portal_staging_workflow_trust.py` reject lost master-only
scoping, mutable checkouts, missing source pin checks, and secrets loaded
before the reviewed integrity/test gates. They are purely offline and do
not prove actual tsidp connectivity or login.
