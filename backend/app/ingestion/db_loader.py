"""
Load the derived catalog + knowledge graph into Postgres.

Called by scripts/build_catalog.py --load-db. Applies the schema first, then bulk-inserts
tables, columns, and join edges. Idempotent: truncates catalog/KG tables before reload so
re-running gives a clean state. Sessions/turns/embeddings are left untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db import apply_schema, get_pool

_SCHEMA_SQL = str(Path(__file__).resolve().parent.parent.parent / "sql" / "schema.sql")


async def load_into_postgres(derived: dict[str, Any]) -> None:
    await apply_schema(_SCHEMA_SQL)
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Clean reload of catalog + KG only
            await conn.execute("TRUNCATE catalog_columns, catalog_tables, schema_joins RESTART IDENTITY CASCADE")

            # Tables
            await conn.executemany(
                """
                INSERT INTO catalog_tables
                    (table_name, module, module_id, description, is_master,
                     is_core_domain, total_columns, primary_key, pk_confidence, pk_rule)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                [
                    (
                        t["table_name"], t["module"], t["module_id"], t["description"],
                        t["is_master"], t["is_core_domain"], t["total_columns"],
                        t["primary_key"], t["pk_confidence"], t["pk_rule"],
                    )
                    for t in derived["tables"]
                ],
            )

            # Columns
            col_rows = [
                (t["table_name"], c["number"], c["field"], c["description"], c["type"], c["length"])
                for t in derived["tables"]
                for c in t["columns"]
            ]
            await conn.executemany(
                """
                INSERT INTO catalog_columns
                    (table_name, column_number, field, description, type, length)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT (table_name, field) DO NOTHING
                """,
                col_rows,
            )

            # Join edges (Knowledge Graph)
            await conn.executemany(
                """
                INSERT INTO schema_joins
                    (from_table, from_col, to_table, to_col, confidence, rule)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT (from_table, from_col, to_table, to_col) DO NOTHING
                """,
                [
                    (e["from_table"], e["from_col"], e["to_table"], e["to_col"], e["confidence"], e["rule"])
                    for e in derived["joins"]
                ],
            )

    print(f"      Inserted {len(derived['tables']):,} tables, "
          f"{len(col_rows):,} columns, {len(derived['joins']):,} join edges.")
