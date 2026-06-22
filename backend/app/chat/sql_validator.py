"""
SQL safety validation via sqlglot AST — the hard guardrail before execution.

Rules:
  SV-001  DML/DDL hard-block: no INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/MERGE/EXEC
  SV-002  Single statement only
  SV-003  Must be a read query (SELECT / WITH / UNION)

Falls back to a keyword scan if sqlglot is unavailable, so the guardrail never
silently disappears.
"""

from __future__ import annotations

import re

try:
    import sqlglot
    from sqlglot import expressions as exp
    _SQLGLOT = True
except ImportError:  # pragma: no cover
    _SQLGLOT = False

_BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|EXEC|EXECUTE|GRANT|REVOKE|SP_)\b",
    re.IGNORECASE,
)


_FORBIDDEN_FIELDS = re.compile(
    r'["\[]?CANCELED["\]]?\s*=',
    re.IGNORECASE,
)


def _fix_union_subquery(sql: str) -> tuple[str, list[str]]:
    """
    Service layer returns HTTP 404 for UNION ALL queries wrapped in a subquery:
      SELECT ... FROM ( SELECT ... UNION ALL SELECT ... ) alias ORDER BY ... LIMIT n

    Rewrite to the flat form that the service layer accepts:
      SELECT ... UNION ALL SELECT ... ORDER BY ... LIMIT n

    Uses paren-depth tracking so it handles nested parens inside the inner queries.
    """
    s = sql.strip()
    if not re.match(r'(?i)^SELECT\b', s):
        return sql, []

    # Find the OUTERMOST FROM ( at paren-depth 0 — skip scalar subqueries in WHERE/ON.
    open_pos = -1
    depth = 0
    i = 0
    while i < len(s):
        c = s[i]
        if c == '(':
            # Check if this paren is preceded by FROM at depth 0
            if depth == 0:
                before = s[:i].rstrip()
                if re.search(r'\bFROM\s*$', before, re.IGNORECASE):
                    open_pos = i
                    break
            depth += 1
        elif c == ')':
            depth -= 1
        i += 1

    if open_pos == -1:
        return sql, []
    depth = 0
    close_pos = -1
    for i in range(open_pos, len(s)):
        if s[i] == '(':
            depth += 1
        elif s[i] == ')':
            depth -= 1
            if depth == 0:
                close_pos = i
                break

    if close_pos == -1:
        return sql, []

    inner = s[open_pos + 1:close_pos].strip()
    after = s[close_pos + 1:].strip()

    # Only rewrite if the inner block actually contains UNION ALL
    if not re.search(r'(?i)\bUNION\s+ALL\b', inner):
        return sql, []

    # after = alias_name [ORDER BY ...] [LIMIT n]
    # Strip the alias (first identifier token)
    after_no_alias = re.sub(r'^\w+\s*', '', after).strip()

    fixed = inner + ('\n' + after_no_alias if after_no_alias else '')
    return fixed, ['Auto-fixed: unwrapped UNION ALL subquery (service layer returns 404 for this pattern).']


_UNION_ALL = re.compile(r'\bUNION\s+ALL\b', re.IGNORECASE)


def sanitize_sql(sql: str) -> tuple[str, list[str]]:
    """Remove known invalid SAP B1 HANA fields/patterns and return (cleaned_sql, warnings)."""
    warnings: list[str] = []

    # Fix 1a: UNION ALL (any form) → HTTP 404. Try to unwrap if wrapped; flag if bare.
    sql, w = _fix_union_subquery(sql)
    warnings.extend(w)
    if _UNION_ALL.search(sql):
        warnings.append(
            "UNION ALL detected — service layer returns HTTP 404 for UNION ALL queries. "
            "Regenerate using CASE-based conditional aggregation instead."
        )

    # Fix 1b: FROM (subquery) alias → HTTP 404 on this service layer.
    # Detect pattern: the outermost FROM is a subquery (not a scalar in WHERE).
    # Flag it so the pipeline retries.
    if not _UNION_ALL.search(sql):  # only check if no UNION ALL (already handled above)
        from_sub = re.search(r'\bFROM\s*\(SELECT\b', sql, re.IGNORECASE)
        # Allow scalar subqueries in WHERE/ON — only flag if it's the main FROM clause
        if from_sub:
            # Check it's not a scalar subquery (those appear after =, >=, IN, etc.)
            before = sql[:from_sub.start()].rstrip()
            if not re.search(r'(=|>=|<=|>|<|IN|NOT\s+IN|\()\s*$', before, re.IGNORECASE):
                warnings.append(
                    "FROM (subquery) detected — service layer returns HTTP 404 for this pattern. "
                    "Regenerate using a flat SELECT with CASE-based aggregation instead."
                )

    # Fix 2: Strip DocStatus filter on ORCT/OVPM — column not reliably queryable on payment tables
    sql = re.sub(
        r'\s+(AND|OR)\s+[T\w]*\.?"?DocStatus"?\s*=\s*\'[^\']*\'(?=(?:[^\']*\'[^\']*\')*[^\']*$)',
        lambda m: m.group(0) if not re.search(r'\b(ORCT|OVPM)\b', sql[:sql.find(m.group(0))], re.IGNORECASE) else "",
        sql,
        flags=re.IGNORECASE,
    )
    # Simpler targeted removal: if FROM "ORCT" or FROM "OVPM" present, strip any DocStatus condition
    if re.search(r'FROM\s+"?(ORCT|OVPM)"?', sql, re.IGNORECASE):
        cleaned = re.sub(
            r'\s+(AND|OR)\s+[T\w]*\.?"?DocStatus"?\s*=\s*\'[^\']*\'',
            "",
            sql,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r'\bWHERE\s+[T\w]*\.?"?DocStatus"?\s*=\s*\'[^\']*\'\s*(AND\s+)?',
            "WHERE ",
            cleaned,
            flags=re.IGNORECASE,
        )
        if cleaned != sql:
            warnings.append("Removed DocStatus filter from payment table (not valid on ORCT/OVPM).")
            sql = cleaned

    # Fix 3: OCRD."State" → OCRD."State1" (SAP B1 uses State1, not State)
    if re.search(r'\bOCRD\b', sql, re.IGNORECASE) and re.search(r'"State"', sql):
        fixed = re.sub(r'"State"', '"State1"', sql)
        if fixed != sql:
            warnings.append('Auto-fixed: "State" → "State1" (correct SAP B1 OCRD column name).')
            sql = fixed

    # Fix 4: Strip any condition using the non-existent CANCELED column
    if _FORBIDDEN_FIELDS.search(sql):
        # Remove the entire AND/OR clause containing CANCELED
        cleaned = re.sub(
            r'\s+(AND|OR)\s+[T\w]*\.?"?CANCELED"?\s*=\s*\'[^\']*\'',
            "",
            sql,
            flags=re.IGNORECASE,
        )
        # Also handle WHERE CANCELED = ... (if it's the only condition)
        cleaned = re.sub(
            r'\s+WHERE\s+[T\w]*\.?"?CANCELED"?\s*=\s*\'[^\']*\'',
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        if cleaned != sql:
            warnings.append("Removed invalid field 'CANCELED' (not in SAP B1 HANA — use DocStatus instead).")
            sql = cleaned
    return sql, warnings


def validate_sql(sql: str) -> tuple[bool, str]:
    """Return (is_valid, error_message). Empty message when valid."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        return False, "Empty SQL."

    if not _SQLGLOT:
        return _keyword_fallback(sql)

    try:
        # Generic ANSI parse — handles HANA double-quoted identifiers + LIMIT.
        # sqlglot has no dedicated HANA dialect; the keyword fallback also blocks DML.
        statements = [s for s in sqlglot.parse(sql) if s is not None]
    except Exception:
        # Parsing failed (HANA-specific syntax) — fall back to the keyword scan.
        return _keyword_fallback(sql)

    if len(statements) != 1:
        return False, "Only a single statement is allowed."

    stmt = statements[0]

    blocked = (
        exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
        exp.Create, exp.Merge, exp.Command,
    )
    for node_type in blocked:
        if stmt.find(node_type) is not None:
            return False, "Only read-only SELECT queries are permitted (DML/DDL blocked)."

    # TruncateTable is named differently across sqlglot versions — guard by name
    if type(stmt).__name__ in ("TruncateTable", "Truncate"):
        return False, "TRUNCATE is not permitted."

    # Top-level must be a read construct
    if not isinstance(stmt, (exp.Select, exp.Union, exp.With, exp.Subquery)):
        return False, "Only SELECT / WITH / UNION queries are permitted."

    return True, ""


def _keyword_fallback(sql: str) -> tuple[bool, str]:
    if ";" in sql.rstrip(";"):
        return False, "Only a single statement is allowed."
    if _BLOCKED_KEYWORDS.search(sql):
        return False, "Only read-only SELECT queries are permitted (DML/DDL blocked)."
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
        return False, "Only SELECT / WITH queries are permitted."
    return True, ""


def enforce_row_limit(sql: str, cap: int) -> str:
    """
    Append a LIMIT if the query has none, so a forgotten LIMIT can't stream millions
    of rows over HTTP (OINV has 3M+ rows). Harmless on aggregates. HANA puts LIMIT last.
    """
    s = sql.strip().rstrip(";").strip()
    if re.search(r"\bLIMIT\b", s, re.IGNORECASE) or re.search(r"\bFETCH\s+FIRST\b", s, re.IGNORECASE):
        return s
    return f"{s}\nLIMIT {cap}"


_SQL_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
# Matches SELECT ... up to (but not including) any trailing plain-English explanation line
_SQL_BARE = re.compile(r"\b(SELECT\b.*?)(?:\n\s*\n|\Z)", re.IGNORECASE | re.DOTALL)


def extract_sql(text: str) -> str:
    """Pull the SQL out of an LLM response — fenced block preferred, then bare SELECT."""
    if not text:
        return ""

    # 1. Last fenced ```sql ... ``` block (last wins in case model self-corrects)
    matches = list(_SQL_FENCE.finditer(text))
    if matches:
        return matches[-1].group(1).strip()

    # 2. Bare SELECT ... (everything from the last SELECT to end of text)
    m = None
    for m in re.finditer(r"\bSELECT\b", text, re.IGNORECASE):
        pass
    if m:
        candidate = text[m.start():].strip()
        # Strip any trailing plain-English sentence after a blank line
        parts = re.split(r"\n\s*\n", candidate, maxsplit=1)
        return parts[0].strip()

    return ""
