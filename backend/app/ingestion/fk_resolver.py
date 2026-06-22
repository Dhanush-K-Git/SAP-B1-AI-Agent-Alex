"""
Foreign-key / join-edge derivation for SAP B1.

Produces a directed join graph: (from_table.from_col) -> (to_table.to_col) with a
confidence score and the rule that fired. This graph IS the Knowledge Graph the runtime
uses to figure out how to join the tables a question touches.

Rules (highest confidence first):
  1. Header -> Line          OINV.DocEntry -> INV1.DocEntry                          0.99
  2. Global FK column        any CardCode -> OCRD.CardCode, ItemCode -> OITM, …      0.78-0.95
  3. Ambiguous FK column     GroupCode -> OCRG only when CardCode also present       0.40-0.70
  4. Generic name->master PK column name equals some master's PK column             0.55

Self-references and FK-to-own-master (e.g. OCRD.CardCode -> OCRD) are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.loader import Catalog, Table
from app.ingestion.pk_resolver import PrimaryKey
from app.ingestion.sapb1_conventions import (
    AMBIGUOUS_FK_COLUMNS,
    GLOBAL_FK_COLUMNS,
    MASTER_PK,
    header_twin,
)


@dataclass(slots=True)
class JoinEdge:
    from_table: str
    from_col: str
    to_table: str
    to_col: str
    confidence: float
    rule: str

    def key(self) -> tuple[str, str, str, str]:
        return (self.from_table, self.from_col, self.to_table, self.to_col)


def resolve_join_edges(
    table: Table,
    catalog: Catalog,
    primary_keys: dict[str, PrimaryKey],
) -> list[JoinEdge]:
    edges: list[JoinEdge] = []
    names = table.column_names()
    seen: set[tuple[str, str, str, str]] = set()

    def add(from_col: str, to_table: str, to_col: str, conf: float, rule: str) -> None:
        if to_table == table.name:
            return  # no self reference
        if not catalog.exists(to_table):
            return  # referenced master not in this schema
        edge = JoinEdge(table.name, from_col, to_table, to_col, conf, rule)
        if edge.key() in seen:
            return
        seen.add(edge.key())
        edges.append(edge)

    # 1. Line table → its document header (the strongest, most common join).
    #    Pick the link column that actually exists on BOTH tables. Most documents
    #    use DocEntry, but journal entries (OJDT/JDT1) link via TransId, and a few
    #    use AbsEntry — so we fall back in that order.
    twin = header_twin(table.name)
    if twin and catalog.exists(twin) and twin != table.name:
        twin_cols = catalog.tables[twin].column_names()
        for link in ("DocEntry", "TransId", "AbsEntry"):
            if link in names and link in twin_cols:
                add(link, twin, link, 0.99, "line_to_header")
                break

    # 2. Global FK columns
    for col_name, (master, master_pk, conf) in GLOBAL_FK_COLUMNS.items():
        if col_name in names:
            # skip mapping a master's own PK back to itself
            if table.name == master:
                continue
            add(col_name, master, master_pk, conf, "global_fk_column")

    # 3. Ambiguous FK columns (context-sensitive)
    for col_name, options in AMBIGUOUS_FK_COLUMNS.items():
        if col_name not in names:
            continue
        if col_name == "GroupCode":
            # BP group only makes sense when the row is about a business partner
            if "CardCode" in names or table.name in ("OCRD", "OCQG", "OCRG"):
                add("GroupCode", "OCRG", "GroupCode", 0.70, "ambiguous_fk_bp_group")
            else:
                add("GroupCode", "OITB", "ItmsGrpCod", 0.40, "ambiguous_fk_item_group")
        else:
            for master, master_pk, conf in options:
                add(col_name, master, master_pk, conf, "ambiguous_fk")

    # 4. Generic: a column whose name equals a known master's PK column
    pk_to_master = {pk: m for m, pk in MASTER_PK.items()}
    for col in table.columns:
        master = pk_to_master.get(col.field)
        if master and master != table.name and col.field not in GLOBAL_FK_COLUMNS:
            add(col.field, master, col.field, 0.55, "generic_pk_name_match")

    return edges


def resolve_all_join_edges(
    catalog: Catalog,
    primary_keys: dict[str, PrimaryKey],
) -> list[JoinEdge]:
    all_edges: list[JoinEdge] = []
    for table in catalog.tables.values():
        all_edges.extend(resolve_join_edges(table, catalog, primary_keys))
    return all_edges


def join_path_between(
    tables: list[str],
    edges: list[JoinEdge],
) -> list[JoinEdge]:
    """
    Given a set of tables a question touches, return the subset of join edges that
    connect any two of them. This is what the runtime hands to Claude so it knows the
    ON clauses. (Direct edges only — sufficient for the demo's typical 2-4 table joins.)
    """
    wanted = set(tables)
    return [e for e in edges if e.from_table in wanted and e.to_table in wanted]
