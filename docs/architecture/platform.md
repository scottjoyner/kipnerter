# Kipnerter Platform Architecture

## Purpose

Kipnerter is the public web and API control plane for Scott's AI ecosystem. It provides a shared interface for browser and iOS clients while keeping private model, graph, voice, and agent infrastructure off the public internet.

## Trust boundaries

1. Public edge: Caddy, web, and API on DigitalOcean.
2. Authenticated application plane: sessions, users, conversations, agent runs, research jobs, admin UI.
3. Private service plane: AssistX, Sophia, LM Studio/Ollama, Neo4j, Redis/workers, MCP servers, ingestion and embedding workers.
4. Tailscale is the preferred transport between DigitalOcean and private services.

## Domain roles

- `kipnerter.com`: public/product UI.
- `api.kipnerter.com`: versioned API for web and iOS.
- `scottjoyner.dev`: authenticated operator/admin UI.
- `admin.scottjoyner.dev`: optional explicit admin alias.

Authorization must be enforced by the API. Hostname-based UI routing is not an authorization mechanism.

## API direction

The browser and Kipnerter iOS should share one contract under `/api/v1` with streaming under `/ws` or SSE where appropriate.

Initial capability namespaces:

- auth
- conversations/chat/models
- agents/runs/events
- sophia
- research
- documents/ingest
- search/embeddings/graph
- services/health
- mcp

## Research and provenance

Ingested knowledge must retain source provenance. Derived records should preserve source URL/repository/file/commit, ingestion run, chunk identity, embedding model/version, entities, and citations so agent answers can resolve back to evidence.

## MCP

MCP endpoints are registered as capabilities, not hard-coded directly into agents. Registry metadata should include transport, endpoint, available tools/resources, required scopes, network scope, and health.

## Migration

The existing `kipnerter/` Java application remains in place during the foundation PR. It is legacy code and should not receive new platform features. Once the new stack is proven and useful assets are inventoried, it can move to `legacy/java-kipnerter/` in a dedicated migration change.
