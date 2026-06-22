"""
Execute generated SQL via the SAP B1 service-layer endpoint (HANA-backed).

Contract (confirmed against the live endpoint):
  GET {service_layer_url}?query={url-encoded SQL}
    success → 200, application/json, a JSON array of row objects:
              [{"CardCode": "...", "CardName": "..."}, ...]
    error   → non-200, body {"status": 403, "message": "sql syntax error: ..."}

The endpoint runs whatever SQL we send against HANA, so the LLM must produce
HANA dialect (double-quoted identifiers, LIMIT, ADD_MONTHS, TO_VARCHAR, FROM DUMMY).

We normalise the array into the same {columns, rows, row_count, truncated} shape the
rest of the pipeline already expects, so result-type detection and charts are unchanged.
"""

from __future__ import annotations

import httpx

from app.config import get_settings


class ServiceLayerError(Exception):
    """Raised when the endpoint returns an error (e.g. SQL syntax error)."""


def _clean_value(v):
    # The endpoint serialises an un-CAST HANA DECIMAL as {} — coerce to None so it
    # doesn't render as "[object Object]". (LLM is instructed to CAST(... AS DOUBLE).)
    if isinstance(v, dict) and not v:
        return None
    return v


def _normalise(data: list[dict], row_cap: int) -> dict:
    truncated = len(data) > row_cap
    rows = [{k: _clean_value(v) for k, v in row.items()} for row in data[:row_cap]]
    # HANA returns every selected column per row (nulls as JSON null), in SELECT order.
    columns = list(rows[0].keys()) if rows else []
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            return str(body.get("message") or body.get("error") or body)
    except ValueError:
        pass
    text = resp.text.strip()
    # HTML error pages (IIS 404, nginx, etc.) — return a short human-readable message.
    if text.lower().startswith("<!doctype") or text.lower().startswith("<html"):
        return f"HTTP {resp.status_code} — service layer endpoint unreachable or returned an error page."
    return text[:500] or f"HTTP {resp.status_code}"


async def execute_query(sql: str, *, url: str | None = None, timeout: float | None = None) -> dict:
    settings = get_settings()
    endpoint = url or settings.service_layer_url
    to = timeout if timeout is not None else settings.service_layer_timeout

    async with httpx.AsyncClient(timeout=to) as client:
        resp = await client.get(endpoint, params={"query": sql})

    if resp.status_code != 200:
        raise ServiceLayerError(_error_message(resp))

    try:
        data = resp.json()
    except ValueError as exc:
        raise ServiceLayerError(f"Non-JSON response from service layer: {exc}") from exc

    # Some error conditions still come back as 200 with an error object.
    if isinstance(data, dict):
        if "message" in data and "status" in data:
            raise ServiceLayerError(str(data["message"]))
        data = [data]  # single object → one-row result
    if not isinstance(data, list):
        raise ServiceLayerError("Unexpected service-layer response shape.")

    return _normalise(data, settings.service_layer_row_cap)
