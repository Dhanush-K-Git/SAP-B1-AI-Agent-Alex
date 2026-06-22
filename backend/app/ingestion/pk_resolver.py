"""
Primary-key derivation for SAP B1 tables.

Resolution cascade (first match wins), with a confidence score and the rule that fired:

  1. Identity column           an auto-increment surrogate key (only 37 tables)      0.99
  2. Known master table        OCRD->CardCode, OITM->ItemCode, …                     0.98
  3. Line table                has DocEntry + LineNum and a header twin → composite  0.95
  4. Document header           DocEntry present (typically column 1)                 0.90
  5. Generic *Code / *Entry    single column ending in Code/Entry/ID + key-ish desc  0.65
  6. Fallback                   column number 1                                       0.40
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.loader import Catalog, Table
from app.ingestion.sapb1_conventions import MASTER_PK, header_twin

_KEY_DESC_HINTS = ("internal number", "code", "key", "abs entry", "entry", "primary")


@dataclass(slots=True)
class PrimaryKey:
    table: str
    columns: list[str]          # composite keys have >1 column
    confidence: float
    rule: str

    @property
    def is_composite(self) -> bool:
        return len(self.columns) > 1


def resolve_primary_key(table: Table, catalog: Catalog) -> PrimaryKey:
    names = table.column_names()

    # 1. Identity surrogate key
    for col in table.columns:
        if col.type.lower() == "identity":
            return PrimaryKey(table.name, [col.field], 0.99, "identity_column")

    # 2. Known master
    if table.name in MASTER_PK:
        pk = MASTER_PK[table.name]
        if pk in names:
            return PrimaryKey(table.name, [pk], 0.98, "known_master")
        # master defined but column absent → still trust the convention
        return PrimaryKey(table.name, [pk], 0.80, "known_master_missing_col")

    # 3. Line table → composite (DocEntry, LineNum)
    if "DocEntry" in names and "LineNum" in names:
        twin = header_twin(table.name)
        if twin and catalog.exists(twin):
            return PrimaryKey(table.name, ["DocEntry", "LineNum"], 0.95, "line_table_composite")
        # has the shape but no header twin → still a composite line-like table
        return PrimaryKey(table.name, ["DocEntry", "LineNum"], 0.80, "line_shape_no_twin")

    # 4. Document header
    if "DocEntry" in names:
        return PrimaryKey(table.name, ["DocEntry"], 0.90, "document_header")

    # 4b. Journal-style header keyed by TransId (e.g. OJDT)
    if "TransId" in names:
        return PrimaryKey(table.name, ["TransId"], 0.85, "transid_header")

    # 5. Generic single key column by name + description hint
    generic = _generic_key_column(table)
    if generic:
        return PrimaryKey(table.name, [generic], 0.65, "generic_key_column")

    # 6. Fallback: first column
    first = min(table.columns, key=lambda c: c.number) if table.columns else None
    if first:
        return PrimaryKey(table.name, [first.field], 0.40, "fallback_first_column")

    return PrimaryKey(table.name, [], 0.0, "no_columns")


def _generic_key_column(table: Table) -> str | None:
    """Pick a likely key column: name ends with Code/Entry/ID and sits early with a key-ish description."""
    candidates: list[tuple[int, str]] = []
    for col in table.columns:
        f = col.field
        fl = f.lower()
        ends_key = fl.endswith(("code", "entry", "id")) or fl in ("absentry", "abs")
        desc_key = any(h in col.description.lower() for h in _KEY_DESC_HINTS)
        if ends_key and (col.number <= 3 or desc_key):
            candidates.append((col.number, f))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def resolve_all_primary_keys(catalog: Catalog) -> dict[str, PrimaryKey]:
    return {name: resolve_primary_key(tbl, catalog) for name, tbl in catalog.tables.items()}
