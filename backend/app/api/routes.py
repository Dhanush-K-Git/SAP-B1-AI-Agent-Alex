"""FastAPI routes — chat (SSE), sessions, schema status, example questions, demo login."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.chat.memory import delete_session, ensure_session, get_session_turns, list_sessions
from app.chat.pipeline import run_question
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
