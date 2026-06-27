"""
SAP B1 Service Layer — transactional actions.

Base URL  : SAP_BASE_URL in .env  (e.g. http://vzone.in:1662)
Auth      : None required (vzone proxy handles it)
SSL       : verify=False (self-signed cert on the server)

Covers:
  Sales Orders   — create / update / cancel / close
  Sales Invoices — create / cancel / close / reopen
  Sales Returns  — create / cancel / close / reopen
  Purchase Orders — create / update / cancel / close
"""

from __future__ import annotations

import httpx

from app.config import get_settings


class SAPActionError(Exception):
    """Raised when the SAP B1 Service Layer returns an error."""


def _base() -> str:
    url = get_settings().sap_sl_base_url
    if not url:
        raise SAPActionError(
            "SAP_SL_BASE_URL is not set in .env. "
            "Add SAP_SL_BASE_URL=http://vzone.in:1662 to enable transactional actions."
        )
    return url.rstrip("/")


def _error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error", {})
            if isinstance(err, dict):
                msg = err.get("message", {})
                if isinstance(msg, dict):
                    return msg.get("value", str(err))
                return str(msg) or str(err)
            return str(err) or str(body)
    except Exception:
        pass
    return resp.text[:300] or f"HTTP {resp.status_code}"


async def _post(endpoint: str, payload: dict | None = None) -> dict:
    """POST with optional JSON body — used for create and action calls."""
    url = f"{_base()}/{endpoint}"
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        resp = await client.post(url, json=payload) if payload is not None else await client.post(url)
    if resp.status_code in (200, 201, 204):
        try:
            return {"success": True, "data": resp.json()}
        except Exception:
            return {"success": True, "message": f"{endpoint} action successful"}
    raise SAPActionError(f"[{resp.status_code}] {_error(resp)}")


async def _patch(endpoint: str, payload: dict) -> dict:
    """PATCH — used for updates."""
    url = f"{_base()}/{endpoint}"
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        resp = await client.patch(url, json=payload)
    if resp.status_code in (200, 204):
        return {"success": True, "message": "Updated successfully"}
    raise SAPActionError(f"[{resp.status_code}] {_error(resp)}")


async def _action(endpoint: str) -> dict:
    """POST with no body — used for Cancel / Close / Reopen."""
    url = f"{_base()}/{endpoint}"
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        resp = await client.post(url)
    if resp.status_code in (200, 204):
        return {"success": True, "message": f"{endpoint} action successful"}
    raise SAPActionError(f"[{resp.status_code}] {_error(resp)}")


# ── SALES ORDERS ──────────────────────────────────────────────────────────────

async def create_sales_order(
    card_code: str, doc_date: str, doc_due_date: str, items: list[dict]
) -> dict:
    """POST /Orders"""
    payload = {
        "CardCode": card_code,
        "DocDate": doc_date,
        "DocDueDate": doc_due_date,
        "DocumentLines": [
            {
                "ItemCode": item["ItemCode"],
                "Quantity": item["Quantity"],
                "UnitPrice": item["UnitPrice"],
            }
            for item in items
        ],
    }
    return await _post("Orders", payload)


async def update_sales_order(doc_entry: int, comments: str) -> dict:
    """PATCH /Orders({DocEntry})"""
    return await _patch(f"Orders({doc_entry})", {"Comments": comments})


async def cancel_sales_order(doc_entry: int) -> dict:
    """POST /Orders({DocEntry})/Cancel"""
    return await _action(f"Orders({doc_entry})/Cancel")


async def close_sales_order(doc_entry: int) -> dict:
    """POST /Orders({DocEntry})/Close"""
    return await _action(f"Orders({doc_entry})/Close")


# ── SALES INVOICES ────────────────────────────────────────────────────────────

async def create_sales_invoice(card_code: str, items: list[dict]) -> dict:
    """POST /Invoices"""
    payload = {
        "CardCode": card_code,
        "DocumentLines": [
            {
                "ItemCode": item["ItemCode"],
                "Quantity": item["Quantity"],
                "TaxCode": item.get("TaxCode", "T1"),
                "UnitPrice": item["UnitPrice"],
            }
            for item in items
        ],
    }
    return await _post("Invoices", payload)


async def cancel_sales_invoice(doc_entry: int) -> dict:
    """POST /Invoices({DocEntry})/Cancel"""
    return await _action(f"Invoices({doc_entry})/Cancel")


async def close_sales_invoice(doc_entry: int) -> dict:
    """POST /Invoices({DocEntry})/Close"""
    return await _action(f"Invoices({doc_entry})/Close")


async def reopen_sales_invoice(doc_entry: int) -> dict:
    """POST /Invoices({DocEntry})/Reopen"""
    return await _action(f"Invoices({doc_entry})/Reopen")


# ── SALES RETURNS ─────────────────────────────────────────────────────────────

async def create_sales_return(card_code: str, items: list[dict]) -> dict:
    """POST /Returns"""
    payload = {
        "CardCode": card_code,
        "DocumentLines": [
            {
                "ItemCode": item["ItemCode"],
                "Quantity": item["Quantity"],
                "TaxCode": item.get("TaxCode", "T1"),
                "UnitPrice": item["UnitPrice"],
            }
            for item in items
        ],
    }
    return await _post("Returns", payload)


async def cancel_sales_return(doc_entry: int) -> dict:
    """POST /Returns({DocEntry})/Cancel"""
    return await _action(f"Returns({doc_entry})/Cancel")


async def close_sales_return(doc_entry: int) -> dict:
    """POST /Returns({DocEntry})/Close"""
    return await _action(f"Returns({doc_entry})/Close")


async def reopen_sales_return(doc_entry: int) -> dict:
    """POST /Returns({DocEntry})/Reopen"""
    return await _action(f"Returns({doc_entry})/Reopen")


# ── PURCHASE ORDERS ───────────────────────────────────────────────────────────

async def create_purchase_order(
    card_code: str, doc_date: str, doc_due_date: str, items: list[dict]
) -> dict:
    """POST /PurchaseOrders"""
    payload = {
        "CardCode": card_code,
        "DocDate": doc_date,
        "DocDueDate": doc_due_date,
        "DocumentLines": [
            {
                "ItemCode": item["ItemCode"],
                "Quantity": item["Quantity"],
                "UnitPrice": item["UnitPrice"],
            }
            for item in items
        ],
    }
    return await _post("PurchaseOrders", payload)


async def update_purchase_order(doc_entry: int, comments: str) -> dict:
    """PATCH /PurchaseOrders({DocEntry})"""
    return await _patch(f"PurchaseOrders({doc_entry})", {"Comments": comments})


async def cancel_purchase_order(doc_entry: int) -> dict:
    """POST /PurchaseOrders({DocEntry})/Cancel"""
    return await _action(f"PurchaseOrders({doc_entry})/Cancel")


async def close_purchase_order(doc_entry: int) -> dict:
    """POST /PurchaseOrders({DocEntry})/Close"""
    return await _action(f"PurchaseOrders({doc_entry})/Close")
