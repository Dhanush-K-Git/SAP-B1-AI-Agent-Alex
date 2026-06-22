"""Short-term session memory — sessions + turns persisted in Postgres."""

from __future__ import annotations

import json
import uuid

import asyncpg


async def ensure_session(pool: asyncpg.Pool, session_id: str | None, title: str | None = None) -> str:
    async with pool.acquire() as conn:
        if session_id:
            row = await conn.fetchrow("SELECT id FROM sessions WHERE id = $1", uuid.UUID(session_id))
            if row:
                return str(row["id"])
        new_id = await conn.fetchval(
            "INSERT INTO sessions (title) VALUES ($1) RETURNING id", title or "New chat"
        )
        return str(new_id)


async def load_recent_turns(pool: asyncpg.Pool, session_id: str, limit: int = 6) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, question, answer, sql, result_json FROM turns
            WHERE session_id = $1 ORDER BY created_at DESC LIMIT $2
            """,
            uuid.UUID(session_id), limit,
        )
    result = []
    for r in reversed(rows):
        d = dict(r)
        if d.get("result_json"):
            try:
                d["result"] = json.loads(d["result_json"])
            except (ValueError, TypeError):
                d["result"] = None
        else:
            d["result"] = None
        del d["result_json"]
        result.append(d)
    return result


async def save_turn(
    pool: asyncpg.Pool,
    session_id: str,
    *,
    question: str,
    thinking: str,
    sql: str,
    answer: str,
    result: dict | None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO turns (session_id, role, question, thinking, sql, answer, result_json)
            VALUES ($1, 'assistant', $2, $3, $4, $5, $6)
            """,
            uuid.UUID(session_id), question, thinking, sql, answer,
            json.dumps(result, default=str) if result else None,
        )


async def get_session_turns(pool: asyncpg.Pool, session_id: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT question, answer, sql, thinking, result_json
            FROM turns
            WHERE session_id = $1 ORDER BY created_at ASC
            """,
            uuid.UUID(session_id),
        )
    turns = []
    for r in rows:
        result = None
        if r["result_json"]:
            try:
                result = json.loads(r["result_json"])
            except (ValueError, TypeError):
                result = None
        turns.append({
            "question": r["question"] or "",
            "answer": r["answer"] or "",
            "sql": r["sql"] or "",
            "thinking": r["thinking"] or "",
            "result": result,
        })
    return turns


async def delete_session(pool: asyncpg.Pool, session_id: str) -> bool:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM turns WHERE session_id = $1", uuid.UUID(session_id))
        result = await conn.execute("DELETE FROM sessions WHERE id = $1", uuid.UUID(session_id))
    return result == "DELETE 1"


async def list_sessions(pool: asyncpg.Pool, limit: int = 50) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, created_at FROM sessions ORDER BY created_at DESC LIMIT $1", limit
        )
    return [{"id": str(r["id"]), "title": r["title"], "created_at": r["created_at"].isoformat()} for r in rows]
