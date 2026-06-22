"""
Build the semantic context block injected into the Claude prompt.

Given the tables retrieved for a question (+ their KG join edges), produce a compact,
business-aware description: what each entity means, its key fields, status-code meanings,
and the exact ON clauses to use. This is what turns "show open invoices by customer" into
correct SAP B1 SQL.
"""

from __future__ import annotations

from app.semantic.entities import Entity, entities_for_tables
from app.ingestion.sapb1_conventions import STATUS_FIELD_VALUES


def build_semantic_context(
    retrieved_tables: list[dict],   # [{table_name, description, primary_key, columns:[{field,description,type}]}]
    join_edges: list[dict],         # [{from_table, from_col, to_table, to_col, confidence}]
) -> str:
    table_names = {t["table_name"] for t in retrieved_tables}
    lines: list[str] = []

    # ── 1. Business entities in play ─────────────────────────────────────────
    entities = entities_for_tables(table_names)
    if entities:
        lines.append("## Business entities")
        for ent in entities:
            lines.append(_describe_entity(ent))
        lines.append("")

    # ── 2. Table schemas (retrieved) ─────────────────────────────────────────
    lines.append("## Tables")
    for t in retrieved_tables:
        pk = ", ".join(t.get("primary_key") or []) or "n/a"
        lines.append(f"### {t['table_name']} — {t.get('description','')}  (PK: {pk})")
        for c in t.get("columns", []):
            desc = f" — {c['description']}" if c.get("description") else ""
            lines.append(f"  - {c['field']} ({c['type']}){desc}")
        lines.append("")

    # ── 3. Join paths (the ON clauses) ───────────────────────────────────────
    if join_edges:
        lines.append("## Join paths (HANA — use these exact ON clauses, keep the quotes)")
        for e in sorted(join_edges, key=lambda x: -x.get("confidence", 0)):
            lines.append(
                f'  - "{e["from_table"]}"."{e["from_col"]}" = "{e["to_table"]}"."{e["to_col"]}"'
            )
        lines.append("")

    # ── 4. Status / enum code meanings for retrieved columns ─────────────────
    status_block = _status_codes_for(retrieved_tables)
    if status_block:
        lines.append("## Status / code meanings")
        lines.extend(status_block)
        lines.append("")

    return "\n".join(lines)


def _describe_entity(ent: Entity) -> str:
    parts = [f"- **{ent.label}** (`{ent.header_table}`"]
    if ent.line_table:
        parts.append(f" header, `{ent.line_table}` lines, joined on `{ent.link_column}`")
    parts.append(")")
    bits: list[str] = []
    if ent.date_field:
        bits.append(f"date={ent.date_field}")
    if ent.amount_field:
        bits.append(f"amount={ent.amount_field}")
    if ent.status_field:
        bits.append(f"status={ent.status_field}")
    if ent.partner_field:
        who = "customer" if ent.partner_type == "C" else "vendor" if ent.partner_type == "S" else "partner"
        bits.append(f"{who}={ent.partner_field}→OCRD")
    line = "".join(parts)
    if bits:
        line += "  [" + ", ".join(bits) + "]"
    if ent.common_filters:
        filt = "; ".join(f"{k}: {v}" for k, v in ent.common_filters.items())
        line += f"\n    filters → {filt}"
    if ent.notes:
        line += f"\n    note → {ent.notes}"
    return line


def _status_codes_for(retrieved_tables: list[dict]) -> list[str]:
    seen_fields: set[str] = set()
    out: list[str] = []
    for t in retrieved_tables:
        for c in t.get("columns", []):
            f = c["field"]
            if f in STATUS_FIELD_VALUES and f not in seen_fields and STATUS_FIELD_VALUES[f]:
                seen_fields.add(f)
                mapping = ", ".join(f"'{k}'={v}" for k, v in STATUS_FIELD_VALUES[f].items())
                out.append(f"  - {f}: {mapping}")
    return out
