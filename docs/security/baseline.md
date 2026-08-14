# Security Baseline

## Principles

- Public exposure terminates at the DigitalOcean edge.
- Internal AI/data services are private by default.
- Authentication and authorization are enforced by the API, not only by UI routing or hostnames.
- Secrets never enter source control.
- Every agent/tool invocation should eventually be auditable.

## Network

Only Caddy should require public 80/443. API and web container ports are published for local development but should be bound privately or filtered on production hosts. Neo4j, Redis, LM Studio, Ollama, AssistX internals, Sophia internals, and MCP servers should not be directly internet-addressable.

Use Tailscale for DigitalOcean-to-private-service connectivity where practical.

## Identity direction

Planned scopes include:

- `chat:use`
- `models:read`
- `agents:run`
- `research:create`
- `documents:upload`
- `graph:read`
- `graph:write`
- `mcp:invoke`
- `services:admin`
- `infrastructure:admin`

Roles and scopes should be explicit; admin hostnames must not bypass authorization.

## Repository hygiene

- `.env` files are ignored.
- `.env.example` contains names only, no credentials.
- CI performs secret scanning.
- Historical repositories such as askHR must be secret-scanned before code/config is copied into Kipnerter.

## Production hardening

Before DNS cutover:

- key-only SSH
- non-root deployment user
- disable password root login
- DigitalOcean Cloud Firewall
- host firewall policy
- monitoring
- snapshots/backups
- rate limits on public API endpoints
- structured audit logs for privileged operations
