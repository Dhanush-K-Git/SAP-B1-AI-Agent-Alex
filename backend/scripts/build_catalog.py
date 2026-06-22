"""
One-time offline build: erpref JSON  →  derived catalog + knowledge graph.

Usage:
    # Inspect-only: write derived catalog/joins/stats to ./output (no database needed)
    python scripts/build_catalog.py --input "C:/Users/MO/Downloads/erpref_cleaned_database.json"

    # Also load into Postgres (requires docker compose up + .env configured)
    python scripts/build_catalog.py --input ".../erpref_cleaned_database.json" --load-db

Run from the backend/ directory so `app` is importable, or set PYTHONPATH=backend.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make `app` importable when run as `python scripts/build_catalog.py` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingestion.catalog_builder import build_derived_schema  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SAP B1 catalog + KG from erpref JSON")
    parser.add_argument("--input", required=True, help="Path to erpref_cleaned_database.json")
    parser.add_argument("--out", default="output", help="Output directory for JSON artifacts")
    parser.add_argument("--load-db", action="store_true", help="Also load into Postgres")
    args = parser.parse_args()

    print(f"[1/3] Loading + deriving schema from: {args.input}")
    derived = build_derived_schema(args.input)
    stats = derived["stats"]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[2/3] Writing artifacts to: {out_dir.resolve()}")
    (out_dir / "catalog.json").write_text(
        json.dumps(derived["tables"], indent=2), encoding="utf-8"
    )
    (out_dir / "joins.json").write_text(
        json.dumps(derived["joins"], indent=2), encoding="utf-8"
    )
    (out_dir / "stats.json").write_text(
        json.dumps(stats, indent=2), encoding="utf-8"
    )

    _print_summary(stats)

    if args.load_db:
        print("[3/3] Loading into Postgres …")
        import asyncio

        from app.ingestion.db_loader import load_into_postgres

        asyncio.run(load_into_postgres(derived))
        print("      Done. Catalog + KG persisted.")
    else:
        print("[3/3] Skipped DB load (pass --load-db to persist). Inspect output/ JSON files.")

    return 0


def _print_summary(stats: dict) -> None:
    print("\n" + "=" * 64)
    print("  DERIVATION SUMMARY")
    print("=" * 64)
    print(f"  Tables ................... {stats['total_tables']:,}")
    print(f"  Columns .................. {stats['total_columns']:,}")
    print(f"  Join edges derived ....... {stats['total_join_edges']:,}")
    print(f"  Tables with joins ........ {stats['tables_with_outgoing_joins']:,}")
    print(f"  Composite primary keys ... {stats['composite_primary_keys']:,}")
    print(f"  Low-confidence PKs ....... {stats['low_confidence_primary_keys']:,}")
    print("\n  PK rule breakdown:")
    for rule, n in sorted(stats["pk_rule_breakdown"].items(), key=lambda x: -x[1]):
        print(f"    {rule:.<34} {n:,}")
    print("\n  Join rule breakdown:")
    for rule, n in sorted(stats["join_rule_breakdown"].items(), key=lambda x: -x[1]):
        print(f"    {rule:.<34} {n:,}")
    print("\n  Most-referenced tables (join targets):")
    for row in stats["most_referenced_tables"]:
        print(f"    {row['table']:.<34} {row['incoming_joins']:,} incoming")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
