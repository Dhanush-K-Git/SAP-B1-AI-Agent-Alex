"""
The text-to-SQL pipeline — orchestrates one question end to end and yields a
stream of typed events (consumed by the SSE endpoint).

  load history → intent (Haiku) → retrieve (pgvector + KG) → build prompt
  → stream SQL with thinking (Sonnet/Opus) → validate (sqlglot) → execute (service layer)
  → detect result type / forecast → summarize → persist turn

Each yielded dict has a "type": thinking | sql_token | sql | result | answer | error | info | done
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator

import asyncpg

from app.chat.claude import ClaudeClient
from app.chat.forecast import linear_forecast
from app.chat.memory import load_recent_turns, save_turn
from app.chat.service_layer import execute_query
from app.chat.result_types import detect_result_type
from app.chat.sql_validator import enforce_row_limit, extract_sql, sanitize_sql, validate_sql
from app.config import Settings
from app.embeddings.provider import EmbeddingProvider
from app.retrieval.retriever import retrieve_context
from app.semantic.builder import build_semantic_context
from app.tools.generator import generate_tools, render_tools_context


async def run_question(
    *,
    pool: asyncpg.Pool,
    provider: EmbeddingProvider,
    claude: ClaudeClient,
    settings: Settings,
    session_id: str,
    question: str,
    model: str,
    thinking: bool,
) -> AsyncIterator[dict]:
    # 1. History (session memory) — loaded first so relevance check has conversation context
    history = await load_recent_turns(pool, session_id, limit=6)

    # 2+3. Classify: SAP B1 question / general knowledge / inappropriate
    rl = await claude.check_relevance_and_intent(question, history=history)

    if not rl.get("relevant", True):
        if rl.get("general", False):
            # General knowledge question — answer directly like ChatGPT, no SQL
            async for chunk in claude.answer_general(question, history=history):
                yield {"type": "answer_token", "text": chunk}
            yield {"type": "answer_done"}
            yield {"type": "done", "session_id": session_id}
        else:
            # Truly inappropriate — polite block
            off_topic_answer = await claude.answer_off_topic(question, model=model)
            yield {"type": "answer", "text": off_topic_answer}
            yield {"type": "done", "session_id": session_id}
        return

    intent = rl  # already contains keywords, entities, intent
    yield {"type": "info", "stage": "intent", "intent": intent.get("intent"), "keywords": intent.get("keywords", [])}

    # 3b. Clarification gate — if question is too vague, ask for more detail
    if await claude.needs_clarification(question, intent):
        clarify_answer = await claude.ask_clarification(question)
        yield {"type": "answer", "text": clarify_answer}
        yield {"type": "done", "session_id": session_id}
        return

    # 4. Retrieval (vector + KG joins)
    ctx = await retrieve_context(pool, provider, question, intent.get("keywords", []))
    yield {"type": "info", "stage": "retrieval",
           "tables": [t["table_name"] for t in ctx["tables"]],
           "joins": len(ctx["joins"])}

    # 5. Build the prompt
    semantic = build_semantic_context(ctx["tables"], ctx["joins"])
    tools_ctx = render_tools_context(generate_tools(), limit=10)
    history_text = _format_history(history)
    user = (
        f"{semantic}\n\n{tools_ctx}\n\n"
        f"{history_text}"
        f"Question: {question}\n\n"
        "Write exactly one SAP HANA SQL SELECT query that answers it "
        "(double-quoted identifiers, LIMIT, CAST money to DOUBLE, anchor relative dates "
        "on the data's MAX date)."
    )

    # 5. Stream SQL generation (thinking + text)
    thinking_buf: list[str] = []
    text_buf: list[str] = []
    async for kind, delta in claude.stream_sql(
        model=model, thinking=thinking, system=claude.sql_system_prompt, user=user
    ):
        if kind == "thinking":
            thinking_buf.append(delta)
            yield {"type": "thinking", "text": delta}
        else:
            text_buf.append(delta)
            yield {"type": "sql_token", "text": delta}

    full_text = "".join(text_buf)
    sql = extract_sql(full_text)

    # 6a. If SQL is empty (thinking used all tokens), retry once without thinking
    if not sql.strip():
        yield {"type": "info", "stage": "retry", "text": "Retrying with direct SQL generation…"}
        thinking_buf.clear()
        text_buf.clear()
        async for kind, delta in claude.stream_sql(
            model=model, thinking=False, system=claude.sql_system_prompt, user=user
        ):
            if kind == "thinking":
                thinking_buf.append(delta)
            else:
                text_buf.append(delta)
                yield {"type": "sql_token", "text": delta}
        full_text = "".join(text_buf)
        sql = extract_sql(full_text)

    # 6b. Sanitize — strip forbidden fields; detect UNION ALL / FROM-subquery
    sql, san_warnings = sanitize_sql(sql)
    for w in san_warnings:
        yield {"type": "info", "stage": "sanitize", "text": w}

    # 6b2. If UNION ALL or FROM (subquery) detected, retry with explicit prohibition
    _needs_retry = any(
        ("UNION ALL detected" in w or "FROM (subquery) detected" in w)
        for w in san_warnings
    )
    if _needs_retry:
        yield {"type": "info", "stage": "retry", "text": "Retrying — rewriting as flat CASE-based query…"}
        yield {"type": "sql_reset"}   # clear accumulated SQL tokens in the UI
        text_buf.clear()
        thinking_buf.clear()
        no_union_note = (
            "\n\nCRITICAL: Your previous SQL used a pattern (UNION ALL or FROM subquery) that causes "
            "HTTP 404 on this server. You MUST rewrite as a single flat SELECT using CASE-based "
            "conditional aggregation (PATTERN 1). No UNION ALL. No FROM (SELECT...). "
            "No subqueries in FROM. Scalar subqueries in WHERE are fine. Single flat SELECT only."
        )
        async for kind, delta in claude.stream_sql(
            model=model, thinking=False,
            system=claude.sql_system_prompt,
            user=user + no_union_note,
        ):
            if kind == "thinking":
                thinking_buf.append(delta)
            else:
                text_buf.append(delta)
                yield {"type": "sql_token", "text": delta}
        full_text = "".join(text_buf)
        sql = extract_sql(full_text)
        sql, san_warnings2 = sanitize_sql(sql)
        for w in san_warnings2:
            yield {"type": "info", "stage": "sanitize", "text": w}
        # If retry STILL has a bad pattern, fail fast with a clear message
        if any(("UNION ALL detected" in w or "FROM (subquery) detected" in w) for w in san_warnings2):
            yield {"type": "error", "text": "Could not generate a valid query for this question. Please rephrase it as a simpler question.", "sql": sql}
            return

    # 6c. Validate
    ok, err = validate_sql(sql)
    if not ok:
        yield {"type": "error", "text": f"Generated SQL rejected: {err}", "sql": sql}
        return
    sql = enforce_row_limit(sql, settings.service_layer_row_cap)
    yield {"type": "sql", "sql": sql}

    # 7. Execute via the SAP B1 service layer (HANA over HTTP)
    result: dict | None = None
    if settings.service_layer_url:
        try:
            result = await execute_query(sql, url=settings.service_layer_url)
        except Exception as exc:  # noqa: BLE001 — surface execution errors to the user
            yield {"type": "error", "text": f"Query execution failed: {exc}", "sql": sql}
            return
    else:
        yield {"type": "info", "stage": "execute",
               "text": "No service-layer endpoint configured — showing the generated query only."}

    # 8. Result-type detection + optional forecast
    if result:
        viz = detect_result_type(result, intent.get("intent"), question)
        if viz["type"] == "forecast":
            values = [
                r[viz["y_col"]] for r in result["rows"]
                if isinstance(r.get(viz["y_col"]), (int, float))
                and not isinstance(r.get(viz["y_col"]), bool)
                and math.isfinite(r[viz["y_col"]])
            ]
            viz["forecast"] = linear_forecast(values, periods_ahead=3)
        yield {"type": "result", "data": result, "viz": viz}

    # 9. Stream the summary — user sees text appearing immediately after SQL executes
    answer_buf: list[str] = []
    async for chunk in claude.stream_summary(question=question, sql=sql, result=result):
        answer_buf.append(chunk)
        yield {"type": "answer_token", "text": chunk}
    answer = "".join(answer_buf).strip()
    yield {"type": "answer_done"}

    # 10. Persist the turn
    await save_turn(pool, session_id, question=question, thinking="".join(thinking_buf), sql=sql, answer=answer, result=result)

    # 11. Follow-up question suggestions (non-blocking — errors here must not crash the stream)
    try:
        suggestions = await claude.generate_follow_up_questions(
            question=question, answer=answer, result=result, model=model
        )
        if suggestions:
            yield {"type": "suggestions", "questions": suggestions}
    except Exception:  # noqa: BLE001
        pass

    yield {"type": "done", "session_id": session_id}


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["Conversation so far (use this context to resolve references like 'these customers', 'that item', etc.):"]
    for t in history[-4:]:
        if t.get("question"):
            lines.append(f"  User: {t['question']}")
        if t.get("answer"):
            # Include a brief version of the answer
            lines.append(f"  Assistant summary: {t['answer'][:300]}")
        # Include key data values from the previous result so the model can resolve "these customers" etc.
        result = t.get("result")
        if result and result.get("rows"):
            rows = result["rows"][:10]
            cols = result.get("columns", [])
            lines.append(f"  Previous data ({len(rows)} rows shown, columns: {cols}):")
            for row in rows[:5]:
                lines.append(f"    {row}")
    return "\n".join(lines) + "\n\n"
