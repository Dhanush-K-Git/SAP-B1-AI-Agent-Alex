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
import re
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
from app.rag.document_store import search_documents
from app.retrieval.retriever import retrieve_context
from app.semantic.builder import build_semantic_context
from app.tools.generator import generate_tools, render_tools_context

_REVIS_REQUEST = re.compile(
    r"\b(chart|graph|plot|visuali[sz]e?|bar|line|pie|graphical|representation|diagram|"
    r"pictorial|visual|show\s+(me\s+)?(a\s+)?(chart|graph|plot|visual|trend)|"
    r"(chart|graph|plot)\s+it|display\s+(as\s+)?(a\s+)?(chart|graph))\b",
    re.IGNORECASE,
)


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

    # 1b. Visualisation shortcut — if user asks to chart/graph the previous result,
    #     reuse it directly instead of running a new SQL query.
    if _REVIS_REQUEST.search(question) and history:
        prev = next((t for t in reversed(history) if t.get("result") and t["result"].get("rows")), None)
        if prev:
            prev_result = prev["result"]
            prev_question = prev.get("question", question)
            viz = detect_result_type(prev_result, intent=None, question=question)
            if viz["type"] == "forecast":
                values = [
                    r[viz["y_col"]] for r in prev_result["rows"]
                    if isinstance(r.get(viz["y_col"]), (int, float))
                    and not isinstance(r.get(viz["y_col"]), bool)
                    and math.isfinite(r[viz["y_col"]])
                ]
                viz["forecast"] = linear_forecast(values, periods_ahead=3)
            yield {"type": "info", "stage": "intent", "text": "Reusing previous result as chart…"}
            yield {"type": "sql", "sql": prev.get("sql", "")}
            yield {"type": "result", "data": prev_result, "viz": viz}
            async for chunk in claude.stream_summary(question=prev_question, sql=prev.get("sql", ""), result=prev_result):
                yield {"type": "answer_token", "text": chunk}
            yield {"type": "answer_done"}
            yield {"type": "done", "session_id": session_id}
            return

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

    # 5b. RAG — search uploaded documents for relevant context
    rag_chunks = await search_documents(pool, provider, question, top_k=4)
    rag_context = ""
    if rag_chunks:
        rag_lines = ["RELEVANT CONTENT FROM UPLOADED DOCUMENTS (use this to supplement your answer):"]
        for chunk in rag_chunks:
            rag_lines.append(f"[{chunk['filename']}]: {chunk['content'][:600]}")
        rag_context = "\n".join(rag_lines) + "\n\n"
        yield {"type": "info", "stage": "rag", "text": f"Found {len(rag_chunks)} relevant section(s) from uploaded documents."}

    user = (
        f"{semantic}\n\n{tools_ctx}\n\n"
        f"{rag_context}"
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
    _has_union_issue = any(
        ("UNION ALL detected" in w or "FROM (subquery) detected" in w)
        for w in san_warnings
    )
    _has_current_date = any("CURRENT_DATE detected" in w for w in san_warnings)
    _needs_retry = _has_union_issue or _has_current_date

    if _needs_retry:
        if _has_current_date:
            retry_note = (
                "\n\nCRITICAL: Your previous SQL used CURRENT_DATE which returns ZERO ROWS because "
                "this database's historical data ends around 2025-03-25. "
                "You MUST replace every CURRENT_DATE with a subquery anchored on the table's max date. "
                "Example: instead of T0.\"DocDate\" >= ADD_DAYS(CURRENT_DATE, -365) "
                "use T0.\"DocDate\" >= ADD_MONTHS((SELECT MAX(\"DocDate\") FROM \"OQUT\"), -12). "
                "Use the SAME table name in the subquery as in the main FROM clause."
            )
        else:
            retry_note = (
                "\n\nCRITICAL: Your previous SQL used a pattern (UNION ALL or FROM subquery) that causes "
                "HTTP 404 on this server. You MUST rewrite as a single flat SELECT using CASE-based "
                "conditional aggregation (PATTERN 1). No UNION ALL. No FROM (SELECT...). "
                "No subqueries in FROM. Scalar subqueries in WHERE are fine. Single flat SELECT only."
            )
        no_union_note = retry_note  # keep variable name for the block below
        yield {"type": "info", "stage": "retry", "text": "Retrying — fixing date anchor in query…" if _has_current_date else "Retrying — rewriting as flat CASE-based query…"}
        yield {"type": "sql_reset"}   # clear accumulated SQL tokens in the UI
        text_buf.clear()
        thinking_buf.clear()
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
        # If CURRENT_DATE retry didn't actually fix it, try once more with a stronger prompt
        if _has_current_date and any("CURRENT_DATE detected" in w for w in san_warnings2):
            yield {"type": "info", "stage": "retry", "text": "CURRENT_DATE still present — retrying with stronger date anchor instruction…"}
            yield {"type": "sql_reset"}
            text_buf.clear()
            stronger_note = (
                "\n\nCRITICAL — DO NOT USE CURRENT_DATE AT ALL. The data in this SAP B1 database "
                "ends around 2025-03-25. CURRENT_DATE is today's date and will return ZERO rows. "
                "You MUST use: ADD_MONTHS((SELECT MAX(\"DocDate\") FROM \"OQUT\"), -12) "
                "Replace every single occurrence of CURRENT_DATE with a MAX-date subquery. "
                "If you use CURRENT_DATE this query WILL FAIL."
            )
            async for kind, delta in claude.stream_sql(
                model=model, thinking=False,
                system=claude.sql_system_prompt,
                user=user + stronger_note,
            ):
                if kind == "text":
                    text_buf.append(delta)
                    yield {"type": "sql_token", "text": delta}
            full_text = "".join(text_buf)
            sql = extract_sql(full_text)
            sql, san_warnings3 = sanitize_sql(sql)
            for w in san_warnings3:
                yield {"type": "info", "stage": "sanitize", "text": w}
            if any("CURRENT_DATE detected" in w for w in san_warnings3):
                yield {"type": "error", "text": "Could not generate a valid date-anchored query. Please try rephrasing your question.", "sql": sql}
                return

    # 6c. Validate — sqlglot structural check
    ok, err = validate_sql(sql)
    if not ok:
        yield {"type": "error", "text": f"Generated SQL rejected: {err}", "sql": sql}
        return

    # 6d. Claude semantic validation — checks if SQL actually answers the question
    cv = await claude.validate_sql_with_claude(question, sql)
    if not cv.get("valid", True):
        issue = cv.get("issue", "SQL does not correctly answer the question.")
        fix = cv.get("fix", "")
        yield {"type": "info", "stage": "validate", "text": f"SQL issue detected — retrying with fix…"}
        yield {"type": "sql_reset"}
        text_buf.clear()
        async for kind, delta in claude.stream_sql(
            model=model, thinking=False,
            system=claude.sql_system_prompt,
            user=user + f"\n\nPREVIOUS SQL HAD AN ISSUE: {issue}. {fix} Please fix it.",
        ):
            if kind == "text":
                text_buf.append(delta)
                yield {"type": "sql_token", "text": delta}
        full_text = "".join(text_buf)
        sql = extract_sql(full_text)
        sql, _ = sanitize_sql(sql)
        ok2, err2 = validate_sql(sql)
        if not ok2:
            yield {"type": "error", "text": f"Generated SQL rejected after retry: {err2}", "sql": sql}
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

    # Signal done first so the UI unlocks (busy=false) immediately after the answer
    yield {"type": "done", "session_id": session_id}

    # 11. Follow-up question suggestions — yielded after done so they pop in without blocking the UI
    try:
        suggestions = await claude.generate_follow_up_questions(
            question=question, answer=answer, result=result, model=model
        )
        if suggestions:
            yield {"type": "suggestions", "questions": suggestions}
    except Exception:  # noqa: BLE001
        pass


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
