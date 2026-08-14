# Kipnerter

Kipnerter is the public web and API control plane for the Kipnerter ecosystem: the companion web experience for `kipnerter-ios`, the public interface for Sophia and AssistX, and the gateway for research, ingestion, embeddings, MCP tools, and private model infrastructure.

## Domains

- `https://kipnerter.com` — public/product experience (DNS cutover pending)
- `https://scottjoyner.dev` — authenticated admin/operator experience
- `https://api.kipnerter.com` — versioned API gateway (DNS cutover pending)

## Architecture

The DigitalOcean edge hosts the internet-facing web/API workloads. Private AI services and data systems remain behind Tailscale and are accessed through explicit service adapters instead of being exposed directly to the internet.

```text
browser / iOS
      |
      v
DigitalOcean edge (Caddy)
      |
      +--> web
      +--> api
             |
             +--> AssistX / Sophia
             +--> research / ingest / MCP
             +--> private Tailscale services
                    +--> LM Studio / Ollama
                    +--> Neo4j
                    +--> Redis / workers
```

## Repository layout

```text
apps/
  web/        public + admin web shell
  api/        FastAPI gateway
infra/
  caddy/      public edge routing
  digitalocean/ deployment notes/topology
  docker/     container support
packages/     shared API/schema packages (next phase)
docs/         architecture, deployment, security, ADRs
kipnerter/    legacy Java application retained during migration
```

## Local development

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Web: `http://localhost:3000`
- API health: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs`

## Current foundation scope

This branch establishes the platform boundary and production topology without committing cloud credentials or changing DNS. Authentication, shared chat/conversation APIs, iOS client integration, AssistX/Sophia adapters, MCP registry, and research/embedding pipelines build on this foundation.

See `docs/architecture/platform.md` and `docs/deployment/digitalocean.md`.
