"""
Detect how a result set should render: KPI card, bar, line, forecast, or table.

Charts (bar/line/forecast) are only chosen when the user explicitly asks for one.
Everything else defaults to table. KPI cards are always shown for single-value results.

Heuristics (only applied when chart requested):
  - 1 row, 1 numeric col            → kpi  (always)
  - 2 cols (label, numeric)         → bar
  - 2 cols (date-ish, numeric)      → line
  - intent forecast + line-shaped   → forecast
"""

from __future__ import annotations

import re

_DATEISH = re.compile(r"(date|month|period|year|day|ym|quarter)", re.IGNORECASE)
_CHART_REQUEST = re.compile(
    r"\b(chart|graph|plot|visuali[sz]e?|bar|line|pie|trend|graphical|representation|diagram|"
    r"draw|pictorial|visual|show\s+(me\s+)?(a\s+)?(chart|graph|plot|visual|trend)|"
    r"(chart|graph|plot)\s+it|display\s+(as\s+)?(a\s+)?(chart|graph))\b",
    re.IGNORECASE,
)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def detect_result_type(result: dict, intent: str | None = None, question: str = "") -> dict:
    cols = result.get("columns", [])
    rows = result.get("rows", [])
    if not rows or not cols:
        return {"type": "table"}

    first = rows[0]
    numeric_cols = [c for c in cols if _is_number(first.get(c))]

    # Single KPI value — always shown as a card regardless of chart request
    if len(rows) == 1 and len(numeric_cols) == 1 and len(cols) <= 2:
        return {"type": "kpi", "label": _non_numeric_label(cols, numeric_cols), "value_col": numeric_cols[0]}

    # Charts when user explicitly asks or intent is trend/forecast
    wants_chart = bool(_CHART_REQUEST.search(question)) or intent in ("trend", "forecast")

    if wants_chart and numeric_cols:
        # Pick best label column (prefer date-ish, else first non-numeric)
        non_numeric = [c for c in cols if c not in numeric_cols]
        label_col = next((c for c in non_numeric if _DATEISH.search(c)), None) or (non_numeric[0] if non_numeric else None)
        value_col = numeric_cols[0]

        if label_col:
            is_time = bool(_DATEISH.search(label_col))
            if intent == "forecast":
                return {"type": "forecast", "x_col": label_col, "y_col": value_col}
            if is_time or intent == "trend":
                return {"type": "line", "x_col": label_col, "y_col": value_col}
            return {"type": "bar", "label_col": label_col, "value_col": value_col}

    return {"type": "table"}


def _non_numeric_label(cols: list[str], numeric_cols: list[str]) -> str | None:
    for c in cols:
        if c not in numeric_cols:
            return c
    return None
