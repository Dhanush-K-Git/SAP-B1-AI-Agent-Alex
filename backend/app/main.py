"""FastAPI application — wires the pool, embedding provider, and Claude client."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.chat.claude import ClaudeClient
from app.config import get_settings
from app.db import close_pool, get_pool
from app.embeddings.provider import get_provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.pool = await get_pool()
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
