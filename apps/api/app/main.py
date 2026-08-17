import asyncio
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .gateway import proxy_request, public_routes, service_health
from .registry import models, services

app = FastAPI(
    title="Kipnerter API",
    version="0.3.0",
    description="Public API gateway for Kipnerter web, iOS, AssistX, Sophia, research, ingestion, and MCP services.",
)

origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "kipnerter-api",
        "environment": os.getenv("KIPNERTER_ENV", "development"),
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["system"])
def ready() -> dict:
    return {"status": "ready"}


@app.get("/api/v1", tags=["system"])
def api_root() -> dict:
    return {
        "name": "Kipnerter API",
        "version": "v1",
        "capabilities": [
            "chat",
            "agents",
            "sophia",
            "research",
            "ingest",
            "embeddings",
            "mcp",
            "services",
            "models",
            "gateway",
        ],
    }


@app.get("/api/v1/services", tags=["platform"])
def list_services() -> dict:
    return {"services": [service.public_dict() for service in services()]}


@app.get("/api/v1/services/health", tags=["platform"])
async def list_service_health() -> dict:
    configured = services()
    results = await asyncio.gather(*(service_health(service) for service in configured))
    return {"services": results}


@app.get("/api/v1/models", tags=["platform"])
def list_models() -> dict:
    return {"models": models()}


@app.get("/api/v1/gateway/routes", tags=["gateway"])
def list_gateway_routes() -> dict:
    return {"routes": public_routes(), "authentication": "bearer"}


@app.api_route(
    "/api/v1/gateway/{service_id}/{upstream_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    tags=["gateway"],
)
async def gateway(service_id: str, upstream_path: str, request: Request) -> Response:
    return await proxy_request(service_id, upstream_path, request)
