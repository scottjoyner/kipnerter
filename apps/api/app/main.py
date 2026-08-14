import os
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .registry import models, services

app = FastAPI(
    title="Kipnerter API",
    version="0.2.0",
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
        ],
    }

@app.get("/api/v1/services", tags=["platform"])
def list_services() -> dict:
    return {"services": [service.public_dict() for service in services()]}

@app.get("/api/v1/models", tags=["platform"])
def list_models() -> dict:
    return {"models": models()}
