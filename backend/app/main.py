"""FastAPI application — wires the pool, embedding provider, and Claude client."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path

from app.api.routes import router
from app.chat.claude import ClaudeClient
from app.config import get_settings
from app.db import apply_schema, close_pool, ensure_rag_tables, get_pool
from app.embeddings.provider import get_provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.pool = await get_pool()
    # Auto-apply schema on every startup (idempotent — uses IF NOT EXISTS)
    schema_path = Path(__file__).parent.parent.parent / "sql" / "schema.sql"
    if schema_path.exists():
        try:
            await apply_schema(str(schema_path))
        except Exception:
            pass  # schema may already be applied; RAG tables created below regardless
    # Ensure RAG tables exist independently (never blocked by other schema errors)
    await ensure_rag_tables()
    app.state.provider = get_provider(settings)
    app.state.claude = ClaudeClient(settings)
    yield
    await close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="SAP B1 Conversational Analytics — MVP", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api")

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
