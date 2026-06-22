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
