"""FastAPI routes — chat (SSE), sessions, schema status, example questions, demo login."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.chat.memory import delete_session, ensure_session, get_session_turns, list_sessions
from app.rag.document_store import delete_document, list_documents, upload_document
from app.chat.pipeline import run_question
from app.chat.sap_actions import (
    SAPActionError,
    # Sales Orders
    create_sales_order, update_sales_order, cancel_sales_order, close_sales_order,
    # Sales Invoices
    create_sales_invoice, cancel_sales_invoice, close_sales_invoice, reopen_sales_invoice,
    # Sales Returns
    create_sales_return, cancel_sales_return, close_sales_return, reopen_sales_return,
    # Purchase Orders
    create_purchase_order, update_purchase_order, cancel_purchase_order, close_purchase_order,
)
from app.config import get_settings
from app.tools.generator import example_questions, generate_tools

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str
    session_id: str | None = None
    model: str = "sonnet"          # "sonnet" | "opus"
    thinking: bool = True


class LoginRequest(BaseModel):
    username: str
    password: str


# ── Demo login (hardcoded) ────────────────────────────────────────────────────
@router.post("/login")
async def login(body: LoginRequest):
    s = get_settings()
    if body.username == s.demo_username and body.password == s.demo_password:
        return {"ok": True, "token": "demo-token"}
    raise HTTPException(status_code=401, detail="Invalid credentials")


# ── Chat (Server-Sent Events) ─────────────────────────────────────────────────
@router.post("/ask")
async def ask(body: AskRequest, request: Request):
    settings = get_settings()
    pool = request.app.state.pool
    provider = request.app.state.provider
    claude = request.app.state.claude

    model = settings.claude_opus_model if body.model == "opus" else settings.claude_default_model
    session_id = await ensure_session(pool, body.session_id, title=body.question[:60])

    async def event_stream():
        # First event carries the resolved session id so the client can pin it.
        yield _sse({"type": "session", "session_id": session_id})
        try:
            async for evt in run_question(
                pool=pool, provider=provider, claude=claude, settings=settings,
                session_id=session_id, question=body.question, model=model, thinking=body.thinking,
            ):
                yield _sse(evt)
        except Exception as exc:  # noqa: BLE001 — never break the stream silently
            yield _sse({"type": "error", "text": f"Pipeline error: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Sessions ──────────────────────────────────────────────────────────────────
@router.get("/sessions")
async def sessions(request: Request):
    return await list_sessions(request.app.state.pool)


@router.get("/sessions/{session_id}/turns")
async def get_turns(session_id: str, request: Request):
    return await get_session_turns(request.app.state.pool, session_id)


@router.delete("/sessions/{session_id}")
async def delete_session_route(session_id: str, request: Request):
    deleted = await delete_session(request.app.state.pool, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


# ── Schema status (for the onboarding / status panel) ────────────────────────
@router.get("/schema/status")
async def schema_status(request: Request):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        tables = await conn.fetchval("SELECT COUNT(*) FROM catalog_tables")
        columns = await conn.fetchval("SELECT COUNT(*) FROM catalog_columns")
        joins = await conn.fetchval("SELECT COUNT(*) FROM schema_joins")
        embedded = await conn.fetchval("SELECT COUNT(*) FROM schema_embeddings")
    return {
        "tables": tables, "columns": columns, "joins": joins, "embeddings": embedded,
        "ready": bool(tables and embedded),
    }


# ── Example questions (for the chat landing screen) ──────────────────────────
@router.get("/example-questions")
async def example_questions_endpoint():
    return example_questions(generate_tools(), per_domain=2)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


# ── RAG Document Upload ───────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "xlsx", "xls", "txt", "csv"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


@router.post("/documents/upload")
async def upload_doc(request: Request, file: UploadFile = File(...)):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 20 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    pool = request.app.state.pool
    provider = request.app.state.provider
    try:
        result = await upload_document(pool, provider, file.filename, data)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/documents")
async def list_docs(request: Request):
    return await list_documents(request.app.state.pool)


@router.delete("/documents/{doc_id}")
async def delete_doc(doc_id: str, request: Request):
    deleted = await delete_document(request.app.state.pool, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"ok": True}


# ── SAP B1 Transactional Actions ──────────────────────────────────────────────
# Requires SAP_SL_BASE_URL=http://vzone.in:1662 in .env

def _sap_error(exc: SAPActionError) -> None:
    raise HTTPException(status_code=502, detail=str(exc))


# ── Request bodies ────────────────────────────────────────────────────────────
class OrderBody(BaseModel):
    card_code: str
    doc_date: str
    doc_due_date: str
    items: list[dict]

class UpdateBody(BaseModel):
    comments: str

class InvoiceBody(BaseModel):
    card_code: str
    items: list[dict]

class ReturnBody(BaseModel):
    card_code: str
    items: list[dict]


# ── Sales Orders ──────────────────────────────────────────────────────────────

@router.post("/sap/sales-orders")
async def sap_create_sales_order(body: OrderBody):
    try:
        return await create_sales_order(body.card_code, body.doc_date, body.doc_due_date, body.items)
    except SAPActionError as e:
        _sap_error(e)


@router.patch("/sap/sales-orders/{doc_entry}")
async def sap_update_sales_order(doc_entry: int, body: UpdateBody):
    try:
        return await update_sales_order(doc_entry, body.comments)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/sales-orders/{doc_entry}/cancel")
async def sap_cancel_sales_order(doc_entry: int):
    try:
        return await cancel_sales_order(doc_entry)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/sales-orders/{doc_entry}/close")
async def sap_close_sales_order(doc_entry: int):
    try:
        return await close_sales_order(doc_entry)
    except SAPActionError as e:
        _sap_error(e)


# ── Sales Invoices ────────────────────────────────────────────────────────────

@router.post("/sap/sales-invoices")
async def sap_create_sales_invoice(body: InvoiceBody):
    try:
        return await create_sales_invoice(body.card_code, body.items)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/sales-invoices/{doc_entry}/cancel")
async def sap_cancel_sales_invoice(doc_entry: int):
    try:
        return await cancel_sales_invoice(doc_entry)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/sales-invoices/{doc_entry}/close")
async def sap_close_sales_invoice(doc_entry: int):
    try:
        return await close_sales_invoice(doc_entry)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/sales-invoices/{doc_entry}/reopen")
async def sap_reopen_sales_invoice(doc_entry: int):
    try:
        return await reopen_sales_invoice(doc_entry)
    except SAPActionError as e:
        _sap_error(e)


# ── Sales Returns ─────────────────────────────────────────────────────────────

@router.post("/sap/sales-returns")
async def sap_create_sales_return(body: ReturnBody):
    try:
        return await create_sales_return(body.card_code, body.items)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/sales-returns/{doc_entry}/cancel")
async def sap_cancel_sales_return(doc_entry: int):
    try:
        return await cancel_sales_return(doc_entry)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/sales-returns/{doc_entry}/close")
async def sap_close_sales_return(doc_entry: int):
    try:
        return await close_sales_return(doc_entry)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/sales-returns/{doc_entry}/reopen")
async def sap_reopen_sales_return(doc_entry: int):
    try:
        return await reopen_sales_return(doc_entry)
    except SAPActionError as e:
        _sap_error(e)


# ── Purchase Orders ───────────────────────────────────────────────────────────

@router.post("/sap/purchase-orders")
async def sap_create_purchase_order(body: OrderBody):
    try:
        return await create_purchase_order(body.card_code, body.doc_date, body.doc_due_date, body.items)
    except SAPActionError as e:
        _sap_error(e)


@router.patch("/sap/purchase-orders/{doc_entry}")
async def sap_update_purchase_order(doc_entry: int, body: UpdateBody):
    try:
        return await update_purchase_order(doc_entry, body.comments)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/purchase-orders/{doc_entry}/cancel")
async def sap_cancel_purchase_order(doc_entry: int):
    try:
        return await cancel_purchase_order(doc_entry)
    except SAPActionError as e:
        _sap_error(e)


@router.post("/sap/purchase-orders/{doc_entry}/close")
async def sap_close_purchase_order(doc_entry: int):
    try:
        return await close_purchase_order(doc_entry)
    except SAPActionError as e:
        _sap_error(e)
