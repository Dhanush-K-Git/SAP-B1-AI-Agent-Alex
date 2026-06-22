"""
Embed the catalog into pgvector for semantic retrieval.

Strategy (matches the confirmed embed scope):
  - ALL tables          → one table-level embedding each (name + description + key columns)
  - core-domain tables  → one embedding PER column as well (precise column-level search)

Reads the catalog from Postgres (populated by build_catalog --load-db), embeds via the
configured provider (Voyage by default), and upserts into schema_embeddings.
"""

from __future__ import annotations

import asyncpg

from app.embeddings.provider import EmbeddingProvider

# How many columns to inline into a table-level embedding (bounds token use).
_MAX_TABLE_COLS = 20


def _vec_literal(vec: list[float]) -> str:
    """Format a Python list as a pgvector text literal: [0.1,0.2,...]."""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


async def _table_level_text(conn: asyncpg.Connection, table: asyncpg.Record) -> str:
    cols = await conn.fetch(
        """
        SELECT field, description FROM catalog_columns
        WHERE table_name = $1 ORDER BY column_number LIMIT $2
        """,
        table["table_name"],
        _MAX_TABLE_COLS,
    )
    col_str = ", ".join(
        f"{c['field']} ({c['description']})" if c["description"] else c["field"]
        for c in cols
    )
    pk = ", ".join(table["primary_key"]) or "n/a"
    return (
        f"Table {table['table_name']} — {table['description']}. "
        f"Module: {table['module']}. Primary key: {pk}. "
        f"Columns: {col_str}"
    )


def _column_level_text(table: asyncpg.Record, col: asyncpg.Record) -> str:
    desc = col["description"] or col["field"]
    return (
        f"Column {table['table_name']}.{col['field']} — {desc}. "
        f"Type: {col['type']}. In table {table['table_name']} "
        f"({table['description']}), module {table['module']}."
    )


async def _upsert(conn: asyncpg.Connection, rows: list[tuple]) -> None:
    """rows = [(kind, table_name, field, content, vec_literal), ...]"""
    await conn.executemany(
        """
        INSERT INTO schema_embeddings (kind, table_name, field, content, embedding)
        VALUES ($1, $2, $3, $4, $5::vector)
        ON CONFLICT (kind, table_name, field)
        DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding
        """,
        rows,
    )


async def embed_catalog(pool: asyncpg.Pool, provider: EmbeddingProvider) -> dict[str, int]:
    """Embed all tables (table-level) + core-domain columns. Returns counts."""
    n_tables = 0
    n_columns = 0

    async with pool.acquire() as conn:
        tables = await conn.fetch(
            "SELECT table_name, module, description, primary_key, is_core_domain FROM catalog_tables ORDER BY table_name"
        )

        # ── Table-level embeddings (batched) ──────────────────────────────────
        # field = '' (not NULL) for table rows so ON CONFLICT (kind, table_name, field)
        # actually matches on re-runs — NULLs are distinct in a Postgres UNIQUE index.
        texts: list[str] = []
        meta: list[str] = []  # table_name
        for t in tables:
            texts.append(await _table_level_text(conn, t))
            meta.append(t["table_name"])

        for batch_texts, batch_meta in _batched(texts, meta, 128):
            vectors = await provider.embed_documents(batch_texts)
            rows = [
                ("table", tname, "", content, _vec_literal(vec))
                for tname, content, vec in zip(batch_meta, batch_texts, vectors)
            ]
            await _upsert(conn, rows)
            n_tables += len(rows)

        # ── Column-level embeddings for core-domain tables ───────────────────
        core_tables = [t for t in tables if t["is_core_domain"]]
        for t in core_tables:
            cols = await conn.fetch(
                "SELECT field, description, type FROM catalog_columns WHERE table_name = $1 ORDER BY column_number",
                t["table_name"],
            )
            col_texts = [_column_level_text(t, c) for c in cols]
            col_fields = [c["field"] for c in cols]
            for batch_texts, batch_fields in _batched(col_texts, col_fields, 128):
                vectors = await provider.embed_documents(batch_texts)
                rows = [
                    ("column", t["table_name"], field, content, _vec_literal(vec))
                    for field, content, vec in zip(batch_fields, batch_texts, vectors)
                ]
                await _upsert(conn, rows)
                n_columns += len(rows)

    return {"tables_embedded": n_tables, "columns_embedded": n_columns}


def _batched(texts: list, meta: list, size: int):
    for i in range(0, len(texts), size):
        yield texts[i : i + size], meta[i : i + size]
