"""asyncpg connection pool + pgvector registration."""

from __future__ import annotations

import asyncpg

from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.pg_dsn,
            min_size=1,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def apply_schema(sql_path: str) -> None:
    """Run sql/schema.sql (idempotent), substituting {{EMBED_DIM}} from settings."""
    from pathlib import Path

    settings = get_settings()
    ddl = Path(sql_path).read_text(encoding="utf-8")
    ddl = ddl.replace("{{EMBED_DIM}}", str(settings.embed_dim))
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(ddl)


async def ensure_rag_tables() -> None:
    """Create RAG tables and indexes if they don't exist — runs independently of schema.sql."""
    settings = get_settings()
    dim = settings.embed_dim
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_documents (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                filename    TEXT NOT NULL,
                file_type   TEXT NOT NULL,
                file_size   INT  NOT NULL DEFAULT 0,
                chunk_count INT  NOT NULL DEFAULT 0,
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id          BIGSERIAL PRIMARY KEY,
                doc_id      UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
                chunk_index INT  NOT NULL,
                content     TEXT NOT NULL,
                embedding   vector({dim}),
                UNIQUE (doc_id, chunk_index)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS ix_rag_chunks_doc ON rag_chunks (doc_id)")
        # HNSW index only works if the column exists and has rows — safe to skip if it already exists
        try:
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS ix_rag_chunks_hnsw
                    ON rag_chunks USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 128)
                    WHERE embedding IS NOT NULL
            """)
        except Exception:
            pass  # index may already exist with same params; harmless to skip
