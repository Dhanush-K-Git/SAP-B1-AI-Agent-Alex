"""
Retrieval: turn a question into the minimal schema slice needed to write SQL.

  question (+ keywords)
    → embed query (Voyage)
    → pgvector search over table-level embeddings  → candidate tables
    → pgvector search over column-level embeddings → surface tables via columns
    → fetch full column lists from the catalog
    → fetch KG join edges connecting those tables

Returns a compact dict the semantic builder turns into prompt context.
"""

from __future__ import annotations

import asyncpg

from app.embeddings.provider import EmbeddingProvider

# Cap columns injected per table so the prompt stays bounded on wide core tables.
_MAX_COLS_PER_TABLE = 40


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


async def retrieve_context(
    pool: asyncpg.Pool,
    provider: EmbeddingProvider,
    question: str,
    keywords: list[str] | None = None,
    *,
    top_tables: int = 15,
    top_columns: int = 12,
) -> dict:
    query_text = question
    if keywords:
        query_text += " " + " ".join(keywords)
    qvec = await provider.embed_query(query_text)
    vlit = _vec_literal(qvec)

    async with pool.acquire() as conn:
        table_hits = await conn.fetch(
            """
            SELECT table_name, 1 - (embedding <=> $1::vector) AS score
            FROM schema_embeddings
            WHERE kind = 'table'
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vlit, top_tables,
        )
        column_hits = await conn.fetch(
            """
            SELECT table_name, 1 - MIN(embedding <=> $1::vector) AS score
            FROM schema_embeddings
            WHERE kind = 'column'
            GROUP BY table_name
            ORDER BY MIN(embedding <=> $1::vector)
            LIMIT $2
            """,
            vlit, top_columns,
        )

        scores: dict[str, float] = {}
        for r in table_hits:
            scores[r["table_name"]] = max(scores.get(r["table_name"], 0), r["score"])
        for r in column_hits:
            scores[r["table_name"]] = max(scores.get(r["table_name"], 0), r["score"])

        names = list(scores.keys())
        tables: list[dict] = []
        for name in names:
            meta = await conn.fetchrow(
                "SELECT table_name, description, primary_key FROM catalog_tables WHERE table_name = $1",
                name,
            )
            if not meta:
                continue
            cols = await conn.fetch(
                """
                SELECT field, description, type FROM catalog_columns
                WHERE table_name = $1 ORDER BY column_number LIMIT $2
                """,
                name, _MAX_COLS_PER_TABLE,
            )
            tables.append({
                "table_name": meta["table_name"],
                "description": meta["description"],
                "primary_key": list(meta["primary_key"] or []),
                "score": round(scores[name], 4),
                "columns": [
                    {"field": c["field"], "description": c["description"], "type": c["type"]}
                    for c in cols
                ],
            })

        tables.sort(key=lambda t: -t["score"])

        joins = await conn.fetch(
            """
            SELECT from_table, from_col, to_table, to_col, confidence
            FROM schema_joins
            WHERE from_table = ANY($1::text[]) AND to_table = ANY($1::text[])
            ORDER BY confidence DESC
            """,
            names,
        )

    return {
        "tables": tables,
        "joins": [dict(j) for j in joins],
    }
