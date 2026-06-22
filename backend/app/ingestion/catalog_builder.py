"""
Orchestrate the offline derivation: load erpref JSON → derive PKs → derive join edges →
assemble a serializable catalog + knowledge-graph + summary stats.

The output of build_derived_schema() is pure data (dicts/lists), so it can be written to
JSON for inspection or loaded into Postgres without any DB dependency here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from app.ingestion.fk_resolver import JoinEdge, resolve_all_join_edges
from app.ingestion.loader import Catalog, load_catalog
from app.ingestion.pk_resolver import PrimaryKey, resolve_all_primary_keys
from app.ingestion.sapb1_conventions import all_core_tables, is_master


def build_derived_schema(json_path: str) -> dict[str, Any]:
    catalog = load_catalog(json_path)
    primary_keys = resolve_all_primary_keys(catalog)
    edges = resolve_all_join_edges(catalog, primary_keys)

    tables_out = _serialize_tables(catalog, primary_keys)
    edges_out = [asdict(e) for e in edges]
    stats = _compute_stats(catalog, primary_keys, edges)

    return {"tables": tables_out, "joins": edges_out, "stats": stats}


def _serialize_tables(
    catalog: Catalog,
    primary_keys: dict[str, PrimaryKey],
) -> list[dict[str, Any]]:
    core = all_core_tables()
    out: list[dict[str, Any]] = []
    for name, tbl in catalog.tables.items():
        pk = primary_keys[name]
        out.append(
            {
                "table_name": name,
                "module": tbl.module,
                "module_id": tbl.module_id,
                "description": tbl.description,
                "is_master": is_master(name),
                "is_core_domain": name in core,
                "total_columns": len(tbl.columns),
                "primary_key": pk.columns,
                "pk_confidence": pk.confidence,
                "pk_rule": pk.rule,
                "columns": [
                    {
                        "number": c.number,
                        "field": c.field,
                        "description": c.description,
                        "type": c.type,
                        "length": c.length,
                    }
                    for c in tbl.columns
                ],
            }
        )
    return out


def _compute_stats(
    catalog: Catalog,
    primary_keys: dict[str, PrimaryKey],
    edges: list[JoinEdge],
) -> dict[str, Any]:
    pk_rules = Counter(pk.rule for pk in primary_keys.values())
    join_rules = Counter(e.rule for e in edges)
    composite = sum(1 for pk in primary_keys.values() if pk.is_composite)
    low_conf_pk = sum(1 for pk in primary_keys.values() if pk.confidence < 0.6)
    tables_with_joins = len({e.from_table for e in edges})
    most_referenced = Counter(e.to_table for e in edges).most_common(15)

    return {
        "total_tables": len(catalog),
        "total_columns": sum(len(t.columns) for t in catalog.tables.values()),
        "total_join_edges": len(edges),
        "tables_with_outgoing_joins": tables_with_joins,
        "composite_primary_keys": composite,
        "low_confidence_primary_keys": low_conf_pk,
        "pk_rule_breakdown": dict(pk_rules),
        "join_rule_breakdown": dict(join_rules),
        "most_referenced_tables": [
            {"table": t, "incoming_joins": n} for t, n in most_referenced
        ],
    }
