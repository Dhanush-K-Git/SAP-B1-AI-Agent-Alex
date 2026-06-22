"""
Tool generation — parameterized SAP HANA SQL query templates derived from the semantic entities.

Each tool is a vetted, business-correct query pattern (SAP HANA dialect: double-quoted
identifiers, LIMIT, ADD_MONTHS/CURRENT_DATE, TO_VARCHAR). They serve
three purposes in the MVP:
  1. Few-shot exemplars injected into the Claude prompt → dramatically better SQL quality.
  2. The example questions surfaced in the chat UI.
  3. Optionally executed directly when a question maps cleanly to a known pattern.

Generation is driven by what each entity supports (amount/date/status/partner fields), so
adding an entity automatically yields its analytical tools.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.semantic.entities import ENTITIES, Entity


@dataclass(slots=True)
class ToolParam:
    name: str
    type: str            # "int" | "string" | "date"
    default: str
    description: str


@dataclass(slots=True)
class Tool:
    name: str
    label: str
    domain: str
    entity: str
    description: str
    example_question: str
    sql_template: str
    params: list[ToolParam] = field(default_factory=list)
    result_type: str = "table"   # "table" | "bar" | "line" | "kpi"


_TOP_N = ToolParam("top_n", "int", "10", "Number of rows to return")
_MONTHS = ToolParam("months", "int", "12", "Look-back window in months")


def generate_tools() -> list[Tool]:
    tools: list[Tool] = []
    for ent in ENTITIES.values():
        tools.extend(_tools_for_entity(ent))
    return tools


def _tools_for_entity(ent: Entity) -> list[Tool]:
    out: list[Tool] = []
    h = ent.header_table
    amount = ent.amount_field
    date = ent.date_field
    status = ent.status_field
    partner = ent.partner_field
    who = "customer" if ent.partner_type == "C" else "vendor" if ent.partner_type == "S" else "partner"

    # ── Document entities (header + amount) ──────────────────────────────────
    if ent.line_table and amount and partner and date:
        out.append(Tool(
            name=f"top_{who}s_by_{ent.name}",
            label=f"Top {who}s by {ent.label}",
            domain=ent.domain, entity=ent.name,
            description=f"Top {who}s ranked by total {ent.label} amount in the look-back window.",
            example_question=f"Who are the top 10 {who}s by {ent.label.lower()} in the last 12 months?",
            sql_template=(
                f'SELECT T1."CardName", CAST(SUM(T0."{amount}") AS DOUBLE) AS "total_amount"\n'
                f'FROM "{h}" T0\n'
                f'JOIN "OCRD" T1 ON T0."{partner}" = T1."CardCode"\n'
                f'WHERE T0."{date}" >= ADD_MONTHS((SELECT MAX("{date}") FROM "{h}"), -{{months}})\n'
                f'GROUP BY T1."CardName"\n'
                f'ORDER BY "total_amount" DESC\n'
                f"LIMIT {{top_n}}"
            ),
            params=[_TOP_N, _MONTHS], result_type="bar",
        ))
        out.append(Tool(
            name=f"{ent.name}_monthly_trend",
            label=f"{ent.label} monthly trend",
            domain=ent.domain, entity=ent.name,
            description=f"Total {ent.label} amount per month over the look-back window.",
            example_question=f"Show the monthly {ent.label.lower()} trend for the last 12 months.",
            sql_template=(
                f"SELECT TO_VARCHAR(T0.\"{date}\", 'YYYY-MM') AS \"period\", "
                f'CAST(SUM(T0."{amount}") AS DOUBLE) AS "total_amount"\n'
                f'FROM "{h}" T0\n'
                f'WHERE T0."{date}" >= ADD_MONTHS((SELECT MAX("{date}") FROM "{h}"), -{{months}})\n'
                f"GROUP BY TO_VARCHAR(T0.\"{date}\", 'YYYY-MM')\n"
                f'ORDER BY "period"'
            ),
            params=[_MONTHS], result_type="line",
        ))

    # ── Open-document list (status field present) ────────────────────────────
    if ent.line_table and status and partner and date and "open" in ent.common_filters:
        out.append(Tool(
            name=f"open_{ent.name}_list",
            label=f"Open {ent.label}s",
            domain=ent.domain, entity=ent.name,
            description=f"List of open {ent.label} documents, most recent first.",
            example_question=f"List the open {ent.label.lower()}s.",
            sql_template=(
                f'SELECT T0."DocNum", T1."CardName", T0."{date}" AS "doc_date", '
                f'CAST(T0."{amount}" AS DOUBLE) AS "total"\n'
                f'FROM "{h}" T0\n'
                f'JOIN "OCRD" T1 ON T0."{partner}" = T1."CardCode"\n'
                f'WHERE T0."{status}" = \'O\'\n'
                f'ORDER BY T0."{date}" DESC\n'
                f"LIMIT {{top_n}}"
            ),
            params=[_TOP_N], result_type="table",
        ))

    # ── Status breakdown ─────────────────────────────────────────────────────
    if status and amount:
        out.append(Tool(
            name=f"{ent.name}_by_status",
            label=f"{ent.label} by status",
            domain=ent.domain, entity=ent.name,
            description=f"Document count and total amount grouped by {status}.",
            example_question=f"Break down {ent.label.lower()}s by status.",
            sql_template=(
                f'SELECT T0."{status}" AS "status", COUNT(*) AS "document_count", '
                f'CAST(SUM(T0."{amount}") AS DOUBLE) AS "total_amount"\n'
                f'FROM "{h}" T0\n'
                f'GROUP BY T0."{status}"'
            ),
            params=[], result_type="bar",
        ))

    # ── Entity-specific master tools ─────────────────────────────────────────
    if ent.name == "item":
        out.append(Tool(
            name="low_stock_items",
            label="Low-stock items",
            domain="inventory", entity="item",
            description="Items whose on-hand quantity is below a threshold.",
            example_question="Which items are low on stock (below 10 units)?",
            sql_template=(
                'SELECT "ItemCode", "ItemName", CAST("OnHand" AS DOUBLE) AS "OnHand", '
                'CAST("OnHand" - "IsCommited" AS DOUBLE) AS "available"\n'
                'FROM "OITM"\n'
                'WHERE "OnHand" < {threshold}\n'
                'ORDER BY "OnHand" ASC\n'
                "LIMIT {top_n}"
            ),
            params=[_TOP_N, ToolParam("threshold", "int", "10", "On-hand threshold")],
            result_type="table",
        ))

    if ent.name in ("customer", "vendor"):
        cardtype = "C" if ent.name == "customer" else "S"
        out.append(Tool(
            name=f"top_{ent.name}s_by_balance",
            label=f"Top {ent.name}s by balance",
            domain=ent.domain, entity=ent.name,
            description=f"{ent.label}s ranked by outstanding balance.",
            example_question=f"Who are the top {ent.name}s by outstanding balance?",
            sql_template=(
                f'SELECT "CardCode", "CardName", CAST("Balance" AS DOUBLE) AS "Balance"\n'
                f'FROM "OCRD"\n'
                f'WHERE "CardType" = \'{cardtype}\'\n'
                f'ORDER BY "Balance" DESC\n'
                f"LIMIT {{top_n}}"
            ),
            params=[_TOP_N], result_type="bar",
        ))

    if ent.name == "gl_account":
        out.append(Tool(
            name="top_account_balances",
            label="Top account balances",
            domain="finance", entity="gl_account",
            description="G/L accounts ranked by current balance (OACT.CurrTotal).",
            example_question="Show the G/L accounts with the largest balances.",
            sql_template=(
                'SELECT "AcctCode", "AcctName", CAST("CurrTotal" AS DOUBLE) AS "balance"\n'
                'FROM "OACT"\n'
                'ORDER BY ABS("CurrTotal") DESC\n'
                "LIMIT {top_n}"
            ),
            params=[_TOP_N], result_type="bar",
        ))

    return out


def render_tools_context(tools: list[Tool], limit: int | None = None) -> str:
    """Render tools as few-shot exemplars for the Claude prompt."""
    chosen = tools if limit is None else tools[:limit]
    lines = ["## Example query patterns (SAP HANA SQL)"]
    for t in chosen:
        lines.append(f"\n-- {t.label}: {t.description}")
        lines.append(f"-- Q: {t.example_question}")
        lines.append(t.sql_template)
    return "\n".join(lines)


def tools_as_dicts(tools: list[Tool]) -> list[dict]:
    return [asdict(t) for t in tools]


def example_questions(tools: list[Tool], per_domain: int = 1) -> list[dict]:
    """Pick a spread of example questions across domains for the UI."""
    by_domain: dict[str, list[Tool]] = {}
    for t in tools:
        by_domain.setdefault(t.domain, []).append(t)
    out: list[dict] = []
    for domain, group in by_domain.items():
        for t in group[:per_domain]:
            out.append({"domain": domain, "question": t.example_question, "tool": t.name})
    return out
