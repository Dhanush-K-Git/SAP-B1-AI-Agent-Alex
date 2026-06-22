"""
Embed the catalog into pgvector. Run AFTER build_catalog.py --load-db.

Usage (from backend/):
    python scripts/build_embeddings.py

Requires: docker compose up (Postgres), .env with VOYAGE_API_KEY + EMBED_* set.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings          # noqa: E402
from app.db import apply_schema, close_pool, get_pool  # noqa: E402
from app.embeddings.embedder import embed_catalog      # noqa: E402
from app.embeddings.provider import get_provider       # noqa: E402

_SCHEMA_SQL = str(Path(__file__).resolve().parent.parent / "sql" / "schema.sql")


async def main() -> int:
    settings = get_settings()
    print(f"Embedding provider: {settings.embed_provider} / {settings.embed_model} ({settings.embed_dim}d)")

    await apply_schema(_SCHEMA_SQL)  # ensure schema_embeddings exists at correct dim
    provider = get_provider(settings)
    pool = await get_pool()

    print("Embedding catalog … (this calls the embedding API in batches of 128)")
    counts = await embed_catalog(pool, provider)
    print(f"  Tables embedded:  {counts['tables_embedded']:,}")
    print(f"  Columns embedded: {counts['columns_embedded']:,}")

    await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
