"""
Claude client for the text-to-SQL pipeline.

Models (per the Claude API reference):
  - Sonnet 4.6 / Opus 4.8 → adaptive thinking via thinking={"type": "adaptive"}.
    budget_tokens is removed on Opus 4.8 (400s); never send temperature/top_p.
  - To show reasoning in the UI, opt into display="summarized" (default is "omitted"
    on Opus 4.8/4.7, so the panel would otherwise be blank).
  - Haiku 4.5 for fast intent extraction.

Streaming reads thinking_delta / text_delta events.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

import anthropic

from app.config import Settings

_INTENT_SYSTEM = (
    "You extract retrieval signals from a business-analytics question about an SAP "
    "Business One database. Respond with ONLY a JSON object, no prose."
)

_RELEVANCE_INTENT_SYSTEM = (
    "You are the first-stage classifier for Alex, an AI assistant at Techative Pvt Ltd.\n"
    "Classify the question into ONE of three categories and respond with ONLY JSON:\n\n"
    "CATEGORY 1 — SAP B1 DATA QUESTION (needs database query):\n"
    "  Questions about sales, invoices, customers, vendors, inventory, AR/AP, payments, purchasing, trends.\n"
    "  Also: follow-up questions using pronouns (his, that, these, same) when prior SAP B1 context exists.\n"
    '  → {"relevant": true, "general": false, "keywords": [...up to 8...], "entities": [...], "intent": "aggregation|trend|lookup|comparison|forecast"}\n\n'
    "CATEGORY 2 — GENERAL KNOWLEDGE QUESTION (answer directly, no database needed):\n"
    "  Anything else a knowledgeable assistant can answer: general knowledge, calculations, explanations,\n"
    "  definitions, business concepts, coding help, geography, science, history, advice, etc.\n"
    '  → {"relevant": false, "general": true, "keywords": [], "entities": [], "intent": "lookup"}\n\n'
    "CATEGORY 3 — HARMFUL / INAPPROPRIATE (should not be answered):\n"
    "  Requests for harmful, illegal, or unethical content only.\n"
    '  → {"relevant": false, "general": false, "keywords": [], "entities": [], "intent": "lookup"}\n\n'
    "Respond with ONLY the JSON object. No prose, no markdown."
)

_GENERAL_SYSTEM = (
    "You are Alex, a highly intelligent AI assistant at Techative Pvt Ltd. "
    "You are knowledgeable about everything — business, technology, science, history, mathematics, "
    "coding, finance, geography, and more. Answer the user's question clearly, accurately, and helpfully.\n\n"
    "FORMAT RULES:\n"
    "- Use **bold** for key terms, important facts, and emphasis.\n"
    "- Use bullet points or numbered lists when listing multiple items.\n"
    "- Use markdown tables when comparing things side by side.\n"
    "- Be concise but thorough — give the right level of detail for the question.\n"
    "- Professional, warm, and direct tone — no unnecessary filler phrases.\n"
    "- No emojis."
)

_SQL_SYSTEM = (
    "You are an expert SAP Business One HANA SQL analyst. "
    "Generate exactly ONE read-only SELECT query inside a ```sql fenced block.\n\n"

    "═══ HANA DIALECT — NON-NEGOTIABLE RULES ═══\n"
    "- Double-quote EVERY table and column identifier: \"OINV\", \"DocTotal\", T0.\"CardCode\".\n"
    "- LIMIT n only (never TOP n). Always add LIMIT unless query is a pure aggregate (no GROUP BY rows to cut).\n"
    "- Date functions: ADD_MONTHS(date, n), ADD_DAYS(date, n), TO_VARCHAR(date,'YYYY-MM'), "
    "YEAR(date), MONTH(date). Never GETDATE(), DATEADD(), FORMAT(), CONVERT().\n"
    "- CAST every money/decimal to DOUBLE before returning: CAST(SUM(T0.\"DocTotal\") AS DOUBLE). "
    "Raw HANA DECIMAL serialises as {} — completely unusable. COUNT(*) is int — no cast needed.\n"
    "- String literals: single quotes only. FROM DUMMY for constant-only SELECTs.\n"
    "- Aliases: T0, T1, T2. Always qualify columns with alias when joining.\n"
    "- NEVER CTEs (WITH … AS) — returns HTTP 403.\n"
    "- NEVER UNION ALL — returns HTTP 404. Use CASE-based conditional aggregation instead (see PATTERN 1).\n"
    "- NEVER SELECT … FROM (subquery) alias — returns HTTP 404. Scalar subqueries in WHERE are fine.\n"
    "- NEVER NULLS LAST/FIRST — use: ORDER BY CASE WHEN col IS NULL THEN 1 ELSE 0 END, col.\n"
    "- NEVER PIVOT, UNPIVOT, EXCEPT, INTERSECT — not supported.\n"
    "- Division: always guard with NULLIF: val / NULLIF(other, 0).\n\n"

    "═══ FORBIDDEN FIELDS (do not exist in SAP B1 HANA — cause HTTP 404) ═══\n"
    "- \"CANCELED\", \"IsCanceled\", \"CancelDate\" → use \"DocStatus\"='C' or 'O'.\n"
    "- \"CustomerName\" on header tables → join to \"OCRD\".\"CardName\".\n"
    "- \"ItemName\" on line tables → join to \"OITM\".\"ItemName\".\n"
    "- \"LineStatus\" on ANY line table (QUT1, RDR1, INV1, POR1, PDN1, etc.) → does not exist, omit it.\n"
    "- \"State\" on OCRD → use \"State1\" (the correct column name).\n"
    "- \"Balance\" on OCRD → virtual/computed field, NOT queryable via SQL. Omit it entirely. "
    "To get outstanding balance use CAST(SUM(T0.\"DocTotal\" - T0.\"PaidToDate\") AS DOUBLE) from OINV or OPCH.\n"
    "- \"CurrTotal\" on OCRD → also not directly queryable. Omit.\n"
    "- \"VatSum\" on OQUT → does not exist on quotation header. Omit.\n"
    "- \"DiscSum\" on OQUT → does not exist on quotation header. Omit.\n"
    "- \"TaxDate\" on OQUT → does not exist on quotation header. Use \"DocDate\".\n"
    "- Never select columns you are not certain exist — if in doubt, omit the column rather than risk a 404.\n\n"

    "═══ NULL FALLBACK RULES ═══\n"
    "- ItemName: always use COALESCE(T1.\"ItemName\", T0.\"ItemCode\") AS \"ItemName\" "
    "so deleted/unmatched items show their code instead of NULL.\n"
    "- CardName: always use COALESCE(T1.\"CardName\", T0.\"CardCode\") AS \"CardName\".\n"
    "- Quantity: if SUM(\"Quantity\") returns NULL (service/non-stock items), "
    "use COALESCE(CAST(SUM(T0.\"Quantity\") AS DOUBLE), 0) AS \"Quantity\".\n"
    "- Never use literal fallback strings like 'Name Unavailable', 'Unknown', or 'N/A' — "
    "always fall back to the code/ID column.\n\n"

    "═══ TABLE-SPECIFIC RULES ═══\n"
    "- ORCT (Incoming Payments): NEVER filter by \"DocStatus\" — this column is not reliably queryable on ORCT. "
    "Query all rows and filter only by \"DocDate\" for period ranges.\n"
    "- OVPM (Outgoing Payments): same rule — no \"DocStatus\" filter.\n"
    "- OINV/ORDR/OQUT: \"DocStatus\" filters ('O'=Open, 'C'=Closed) ARE valid on these tables.\n\n"

    "═══ DATA WINDOW ═══\n"
    "Historical data ends ~2025-03-25. NEVER filter by CURRENT_DATE — returns zero rows. "
    "Always anchor on: (SELECT MAX(\"DocDate\") FROM <table>) for relative windows.\n\n"

    "═══ SAP B1 COMPLETE TABLE REFERENCE ═══\n"
    "SALES:\n"
    "  OQUT/QUT1   = Sales Quotation header/lines\n"
    "  ORDR/RDR1   = Sales Order header/lines\n"
    "  ODLN/DLN1   = Delivery Note header/lines\n"
    "  OINV/INV1   = AR Invoice (sales invoice) header/lines\n"
    "  ORDN/RDN1   = Sales Return header/lines\n"
    "  ORIN/RIN1   = AR Credit Note header/lines\n"
    "PURCHASING:\n"
    "  OPOR/POR1   = Purchase Order header/lines\n"
    "  OPDN/PDN1   = Goods Receipt PO header/lines\n"
    "  OPCH/PCH1   = AP Invoice (purchase invoice) header/lines\n"
    "  ORPC/RPC1   = AP Credit Note header/lines\n"
    "PAYMENTS:\n"
    "  ORCT        = Incoming Payments (customer payments received)\n"
    "                Key cols: DocDate, DocTotal, CardCode, CashSum, TrsfrSum, CheckSum, DocStatus\n"
    "  OVPM        = Outgoing Payments (vendor payments made)\n"
    "                Key cols: DocDate, DocTotal, CardCode, CashSum, TrsfrSum, CheckSum\n"
    "MASTERS:\n"
    "  OCRD        = Business Partner master\n"
    "                CardCode, CardName, CardType ('C'=Customer 'S'=Vendor 'L'=Lead)\n"
    "                Address cols: City, State1 (NOT 'State'!), Country, ZipCode\n"
    "                NOTE: The state column is State1 — never use State (does not exist).\n"
    "  OITM        = Item Master (ItemCode, ItemName, OnHand, ItmsGrpCod)\n"
    "  OITB        = Item Group (ItmsGrpCod, ItmsGrpNam)\n"
    "  OACT        = G/L Account (AcctCode, AcctName, CurrTotal)\n"
    "  OWTQ/WTQ1   = Goods Receipt (inventory in) header/lines\n"
    "  OIGE/IGE1   = Goods Issue (inventory out) header/lines\n"
    "COMMON HEADER COLS: DocEntry, DocNum, DocDate, DocDueDate, CardCode, DocTotal, "
    "DocStatus ('O'=Open, 'C'=Closed), PaidToDate (AR/AP), TaxDate\n"
    "COMMON LINE COLS: DocEntry, LineNum, ItemCode, Dscription (no 'e'!), Quantity, Price, LineTotal, WhsCode\n\n"

    "═══ QUERY PATTERN RULES ═══\n\n"

    "PATTERN 1 — COMPARISON / WHY DID X CHANGE:\n"
    "When user asks 'why did X increase/decrease', 'compare month A vs month B', 'what changed': "
    "ALWAYS fetch BOTH periods in ONE query using conditional aggregation. Example:\n"
    "  SELECT T1.\"CardName\",\n"
    "    CAST(SUM(CASE WHEN TO_VARCHAR(T0.\"DocDate\",'YYYY-MM')='2024-07' THEN T0.\"DocTotal\" ELSE 0 END) AS DOUBLE) AS \"Jul_2024\",\n"
    "    CAST(SUM(CASE WHEN TO_VARCHAR(T0.\"DocDate\",'YYYY-MM')='2024-08' THEN T0.\"DocTotal\" ELSE 0 END) AS DOUBLE) AS \"Aug_2024\",\n"
    "    CAST(SUM(CASE WHEN TO_VARCHAR(T0.\"DocDate\",'YYYY-MM')='2024-08' THEN T0.\"DocTotal\" ELSE 0 END) AS DOUBLE)\n"
    "    - CAST(SUM(CASE WHEN TO_VARCHAR(T0.\"DocDate\",'YYYY-MM')='2024-07' THEN T0.\"DocTotal\" ELSE 0 END) AS DOUBLE) AS \"Change\"\n"
    "  FROM \"ORCT\" T0 INNER JOIN \"OCRD\" T1 ON T0.\"CardCode\"=T1.\"CardCode\"\n"
    "  WHERE TO_VARCHAR(T0.\"DocDate\",'YYYY-MM') IN ('2024-07','2024-08')\n"
    "  GROUP BY T1.\"CardName\" ORDER BY \"Change\" DESC LIMIT 20\n\n"

    "PATTERN 2 — TREND (month-by-month):\n"
    "  SELECT TO_VARCHAR(T0.\"DocDate\",'YYYY-MM') AS \"Period\",\n"
    "    COUNT(*) AS \"Count\",\n"
    "    CAST(SUM(T0.\"DocTotal\") AS DOUBLE) AS \"Total\"\n"
    "  FROM \"OINV\" T0\n"
    "  WHERE T0.\"DocDate\" >= ADD_MONTHS((SELECT MAX(\"DocDate\") FROM \"OINV\"), -12)\n"
    "  GROUP BY TO_VARCHAR(T0.\"DocDate\",'YYYY-MM')\n"
    "  ORDER BY \"Period\"\n\n"

    "PATTERN 3 — TOP N RANKING:\n"
    "  SELECT T1.\"CardName\", COUNT(*) AS \"Orders\",\n"
    "    CAST(SUM(T0.\"DocTotal\") AS DOUBLE) AS \"Total\"\n"
    "  FROM \"ORDR\" T0 INNER JOIN \"OCRD\" T1 ON T0.\"CardCode\"=T1.\"CardCode\"\n"
    "  WHERE T0.\"DocDate\" >= ADD_MONTHS((SELECT MAX(\"DocDate\") FROM \"ORDR\"), -12)\n"
    "  GROUP BY T1.\"CardName\" ORDER BY \"Total\" DESC LIMIT 10\n\n"

    "PATTERN 4 — INCOMING PAYMENTS (use ORCT, not OINV):\n"
    "  SELECT TO_VARCHAR(T0.\"DocDate\",'YYYY-MM') AS \"Period\",\n"
    "    CAST(SUM(T0.\"DocTotal\") AS DOUBLE) AS \"TotalReceived\",\n"
    "    CAST(SUM(T0.\"CashSum\") AS DOUBLE) AS \"Cash\",\n"
    "    CAST(SUM(T0.\"TrsfrSum\") AS DOUBLE) AS \"Transfer\"\n"
    "  FROM \"ORCT\" T0\n"
    "  WHERE T0.\"DocDate\" >= ADD_MONTHS((SELECT MAX(\"DocDate\") FROM \"ORCT\"), -12)\n"
    "  GROUP BY TO_VARCHAR(T0.\"DocDate\",'YYYY-MM') ORDER BY \"Period\"\n\n"

    "PATTERN 5 — PERIOD-OVER-PERIOD TREND (return all months; let the summary compute % change):\n"
    "  SELECT TO_VARCHAR(T0.\"DocDate\",'YYYY-MM') AS \"Period\",\n"
    "    COUNT(*) AS \"PaymentCount\",\n"
    "    CAST(SUM(T0.\"DocTotal\") AS DOUBLE) AS \"TotalReceived\"\n"
    "  FROM \"ORCT\" T0\n"
    "  WHERE T0.\"DocDate\" >= ADD_MONTHS((SELECT MAX(\"DocDate\") FROM \"ORCT\"), -13)\n"
    "  GROUP BY TO_VARCHAR(T0.\"DocDate\",'YYYY-MM')\n"
    "  ORDER BY \"Period\" LIMIT 24\n\n"

    "PATTERN 6 — MULTI-TABLE BREAKDOWN using CASE (instead of UNION ALL which causes HTTP 404):\n"
    "  When asked to compare invoices vs orders, use CASE on the same table or separate queries.\n"
    "  For invoice vs payment comparison by customer:\n"
    "  SELECT T1.\"CardName\",\n"
    "    CAST(SUM(CASE WHEN T0.\"DocDate\" >= ADD_MONTHS((SELECT MAX(\"DocDate\") FROM \"OINV\"),-12) THEN T0.\"DocTotal\" ELSE 0 END) AS DOUBLE) AS \"InvoiceTotal\"\n"
    "  FROM \"OINV\" T0 INNER JOIN \"OCRD\" T1 ON T0.\"CardCode\"=T1.\"CardCode\"\n"
    "  GROUP BY T1.\"CardName\" ORDER BY \"InvoiceTotal\" DESC LIMIT 20\n\n"

    "DOCUMENT CONVERSION CHAIN:\n"
    "- Quotation → Order → Invoice. DocStatus='C' means closed/converted.\n"
    "- QUT1.TargetType: 17=Order, 13=Invoice. QUT1.TrgetEntry = target DocEntry.\n"
    "- INV1.BaseType: 23=Quotation, 17=Order. INV1.BaseEntry = source DocEntry.\n\n"

    "COMPLEXITY LIMIT: Max 2 levels of subquery nesting. Prefer CASE-based aggregation over multiple JOINs.\n\n"
    "NEVER write INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/MERGE/EXEC.\n"
    "After the SQL block, write ONE plain-English sentence explaining what the query returns."
)

_SUMMARY_SYSTEM = (
    "You are Alex, a senior SAP B1 Business Intelligence Analyst at Techative Pvt Ltd.\n\n"

    "OUTPUT EXACTLY THESE 4 BLOCKS IN ORDER — NOTHING ELSE:\n\n"

    "BLOCK 1 — TITLE\n"
    "Write one bold title line. Example: **Top 10 Customers by Sales Quotation — Last 12 Months**\n"
    "Rules: No sentence before or after the title. No acknowledgement. Just the title.\n\n"

    "BLOCK 2 — SUMMARY\n"
    "Write the word SUMMARY on its own line, then 2-3 bold sentences of prose ONLY.\n"
    "Rules:\n"
    "- Prose sentences only. No pipe characters. No table rows. No bullet points.\n"
    "- State the most important finding, the overall pattern, and one business implication.\n"
    "- Only use data that exists in the result. Never invent figures.\n\n"

    "BLOCK 3 — DATA TABLE\n"
    "Write one clean Markdown table.\n"
    "Rules:\n"
    "- Must have: header row | separator row (|---|---|) | data rows.\n"
    "- Maximum 10 rows. Pick the most relevant ones.\n"
    "- Maximum 5 columns. Pick the most important ones.\n"
    "- Do NOT bold cell values inside the table.\n"
    "- Do NOT put the report title inside the table.\n"
    "- Add a TOTAL row at the bottom only if it adds clear value.\n\n"

    "BLOCK 4 — KEY INSIGHTS\n"
    "Write the words KEY INSIGHTS on its own line, then exactly 3 bullet points.\n"
    "Rules for EACH bullet:\n"
    "- One sentence only.\n"
    "- Must contain at least one specific bold figure.\n"
    "- No pipe characters ( | ) anywhere in bullets.\n"
    "- No table rows inside bullets.\n"
    "- No report titles or section headings inside bullets.\n"
    "- No repeating what the SUMMARY already said.\n\n"

    "STOP after the third bullet. Write nothing after it.\n"
    "Do NOT write KEY INSIGHTS twice. Do NOT repeat any block.\n\n"

    "═══ DATA RULES ═══\n"
    "- Only report what is in the result data. Never fabricate missing rows or periods.\n"
    "- If fewer than 3 rows exist: say so and note a trend cannot be established.\n"
    "- If zero rows: write No records found and state the most likely reason.\n\n"

    "═══ FORMAT RULES ═══\n"
    "- Currency: Rs. 2,60,22,142 (Indian format). Bold all figures in prose.\n"
    "- Percentages: +27.6% with sign. Bold in prose.\n"
    "- No emojis. No SQL terms. No column names. No technical jargon.\n"
    "- Never say 'the dataset', 'the query', or 'the result set'."
)

_RELEVANCE_SYSTEM = (
    "You are a relevance filter for an SAP Business One analytics assistant named Alex at Techative Pvt Ltd. "
    "Determine if the user's question is about business data answerable from an SAP B1 database: "
    "sales orders, invoices, customers, vendors, inventory, purchasing, finance, AR/AP, items, trends, forecasts, returns.\n\n"
    "IMPORTANT RULES:\n"
    "- If the conversation history shows the user was discussing SAP B1 data and the new question uses "
    "pronouns or references like 'his', 'her', 'their', 'its', 'that', 'this', 'the same', 'what about', "
    "'how about him/her', 'what is his/her amount' — treat it as RELEVANT because it follows from the prior context.\n"
    "- Short or vague follow-up questions in an ongoing SAP B1 conversation are ALWAYS relevant.\n"
    "- Only return false for questions clearly unrelated to business data (weather, coding, personal advice, etc.) "
    "with NO prior SAP B1 conversation context.\n"
    'Respond with ONLY a JSON object: {"relevant": true} or {"relevant": false}.'
)

_CLARIFY_SYSTEM = (
    "You are **Alex**, a professional SAP B1 Sales Intelligence Assistant at Techative Pvt Ltd. "
    "The user's question is too vague for you to generate a precise database query. "
    "Respond in Markdown with **bold** text. "
    "In 1-2 sentences, acknowledge what they might be asking and explain what extra detail you need. "
    "Then list **2-3 specific clarifying questions** as a bold numbered list to help them be more precise. "
    "Keep it concise, warm, and professional — no emojis."
)

_OFF_TOPIC_SYSTEM = (
    "You are **Alex**, a professional SAP B1 Sales Intelligence Assistant at Techative Pvt Ltd. "
    "The user has asked something outside your scope. Respond in Markdown with **bold** text throughout. "
    "Politely explain in 2-3 sentences that you specialize in SAP Business One analytics — "
    "sales, invoices, inventory, customers, purchasing, and finance — and cannot answer this type of question. "
    "Then suggest **3 example questions** they could ask, formatted as a bold numbered list. "
    "Be warm, professional, and concise — no emojis."
)

_FOLLOWUP_SYSTEM = (
    "You are a business analytics assistant for SAP Business One at Techative Pvt Ltd. "
    "Given a user's question, the answer, and the actual data rows returned, generate exactly 3 follow-up questions.\n\n"
    "STRICT RULES:\n"
    "1. SELF-CONTAINED — each question must name specific entities (customer names, periods, amounts) "
    "taken directly from the data rows. NEVER use vague references like 'these customers', 'this item', 'the above'.\n"
    "2. SIMPLE — each question must be answerable with a single straightforward SQL query: "
    "a Top-N ranking, a monthly trend, or a single-period lookup. "
    "NEVER generate questions that require comparing two tables or UNION ALL queries.\n"
    "3. SAFE PATTERNS ONLY — stick to these types:\n"
    "   - 'Show monthly trend for [specific customer] over last 6 months'\n"
    "   - 'Who are the top 10 customers by [metric] in [specific month]?'\n"
    "   - 'What was the total [metric] for [specific customer] in [specific period]?'\n"
    "   - 'Which items did [specific customer] purchase most in [year]?'\n"
    "4. If specific customer names are in the data, USE THEM.\n\n"
    "Respond with ONLY a JSON array of 3 strings, no prose.\n"
    'Example: ["Show monthly incoming payment trend for Alpha Corp over last 6 months", '
    '"Who are the top 10 customers by incoming payments in October 2024?", '
    '"What was the total payment received from Beta Ltd in 2024?"]'
)


class ClaudeClient:
    def __init__(self, settings: Settings):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._settings = settings

    # ── Stage 0: relevance + intent in ONE Haiku call (saves one round-trip) ───
    async def check_relevance_and_intent(
        self, question: str, history: list[dict] | None = None
    ) -> dict:
        """Returns {relevant, keywords, entities, intent} in a single Haiku call."""
        ctx = ""
        if history:
            ctx = "Recent conversation:\n" + "\n".join(
                f"  User: {t.get('question', '')}\n  Assistant: {t.get('answer', '')[:150]}"
                for t in history[-3:]
                if t.get("question")
            ) + "\n\n"
        user = f"{ctx}Question: {question}"
        resp = await self._client.messages.create(
            model=self._settings.claude_fast_model,
            max_tokens=400,
            system=_RELEVANCE_INTENT_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return _safe_json(
            text,
            default={"relevant": True, "keywords": [], "entities": [], "intent": "lookup"},
        )

    # ── Stage 1: intent + keywords (fast, Haiku) ─────────────────────────────
    async def extract_intent(self, question: str, history: list[dict] | None = None) -> dict:
        ctx = ""
        if history:
            ctx = "Recent conversation:\n" + "\n".join(
                f"{t['role']}: {t.get('question') or t.get('answer') or ''}" for t in history[-4:]
            ) + "\n\n"
        user = (
            f"{ctx}Question: {question}\n\n"
            'Return JSON: {"keywords": [up to 8 schema/business search terms], '
            '"entities": [SAP B1 entities like "ar_invoice","customer"], '
            '"intent": "aggregation|trend|lookup|comparison|forecast"}'
        )
        resp = await self._client.messages.create(
            model=self._settings.claude_fast_model,
            max_tokens=400,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return _safe_json(text, default={"keywords": [], "entities": [], "intent": "lookup"})

    # ── Stage 2: SQL generation (streamed, with thinking) ────────────────────
    async def stream_sql(
        self, *, model: str, thinking: bool, system: str, user: str
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield ("thinking", delta) and ("text", delta) as the model streams."""
        if thinking:
            if "opus" in model.lower():
                # Opus: adaptive with display so the panel isn't blank; give it more room
                thinking_cfg: dict = {"type": "adaptive", "display": "summarized"}
                max_tok = 16000
            else:
                # Sonnet: fixed budget cap — 5 000 tokens is enough for any SQL query.
                # Adaptive can burn 10 000+ tokens on a simple question; this cuts it by ~60%.
                thinking_cfg = {"type": "enabled", "budget_tokens": 5000}
                max_tok = 9000  # 5 000 thinking + 4 000 text (complex CASE queries need room)
        else:
            thinking_cfg = {}
            max_tok = 4000  # pure text, no thinking overhead

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tok,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if thinking:
            kwargs["thinking"] = thinking_cfg

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    d = event.delta
                    if d.type == "thinking_delta":
                        yield ("thinking", d.thinking)
                    elif d.type == "text_delta":
                        yield ("text", d.text)

    @property
    def sql_system_prompt(self) -> str:
        return _SQL_SYSTEM

    # ── Stage 3: natural-language summary — STREAMED for instant perceived response ──
    async def stream_summary(
        self, *, question: str, sql: str, result: dict | None
    ):
        """Yield text chunks as they arrive so the UI can render the answer progressively."""
        if result is None:
            preview = "(no live database connected — SQL was generated but not executed)"
        else:
            rows = result.get("rows", [])
            row_count = result.get("row_count", len(rows))
            truncated = result.get("truncated", False)
            preview = json.dumps(rows[:15], default=str)
            if len(rows) > 15 or truncated:
                preview += f"\n... (showing top 15 of {row_count} rows)"
        user = (
            f"Question: {question}\n\n"
            f"Result data (JSON): {preview}\n\n"
            "Write the structured business summary."
        )
        # Sonnet for quality markdown tables; streamed so the user sees text immediately.
        async with self._client.messages.stream(
            model=self._settings.claude_default_model,
            max_tokens=3000,
            system=_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk

    async def summarize_results(
        self, *, question: str, sql: str, result: dict | None, model: str
    ) -> str:
        """Non-streaming fallback — collects full summary."""
        chunks = []
        async for chunk in self.stream_summary(question=question, sql=sql, result=result):
            chunks.append(chunk)
        return "".join(chunks).strip()


    async def answer_general(self, question: str, history: list[dict] | None = None):
        """Stream an answer to a general knowledge question (no SQL needed)."""
        messages = []
        if history:
            for t in history[-4:]:
                if t.get("question"):
                    messages.append({"role": "user", "content": t["question"]})
                if t.get("answer"):
                    messages.append({"role": "assistant", "content": t["answer"][:500]})
        messages.append({"role": "user", "content": question})
        async with self._client.messages.stream(
            model=self._settings.claude_default_model,
            max_tokens=1500,
            system=_GENERAL_SYSTEM,
            messages=messages,
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk

    async def needs_clarification(self, question: str, intent: dict) -> bool:
        """Return True if the question is too vague to generate reliable SQL."""
        keywords = intent.get("keywords", [])
        q = question.strip()
        # Very short question with no keywords extracted → likely vague
        if len(q.split()) <= 3 and len(keywords) == 0:
            return True
        # Keywords exist but question has no actionable entity or metric
        vague_patterns = re.compile(
            r"^\s*(show|give|get|tell|list|find|what|how|which)\s+(me\s+)?(the\s+)?(data|info|information|details|report|numbers?|stats?|analytics?)\s*\??$",
            re.IGNORECASE,
        )
        if vague_patterns.match(q):
            return True
        return False

    async def ask_clarification(self, question: str) -> str:
        """Generate a clarifying response asking the user to be more specific."""
        resp = await self._client.messages.create(
            model=self._settings.claude_fast_model,
            max_tokens=300,
            system=_CLARIFY_SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    async def check_relevance(self, question: str, history: list[dict] | None = None) -> bool:
        """Return True if the question is about SAP B1 business data."""
        # Build context from recent history so pronouns like "his", "that" can be resolved
        ctx = ""
        if history:
            ctx = "Recent conversation:\n" + "\n".join(
                f"  User: {t.get('question', '')}\n  Assistant: {t.get('answer', '')[:150]}"
                for t in history[-3:]
                if t.get("question")
            ) + "\n\n"

        content = f"{ctx}New question: {question}"
        resp = await self._client.messages.create(
            model=self._settings.claude_fast_model,
            max_tokens=50,
            system=_RELEVANCE_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        result = _safe_json(text, default={"relevant": True})
        return bool(result.get("relevant", True))

    async def answer_off_topic(self, question: str, model: str) -> str:
        """Return a polite, bold-formatted off-topic response."""
        resp = await self._client.messages.create(
            model=self._settings.claude_fast_model,
            max_tokens=300,
            system=_OFF_TOPIC_SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    async def generate_follow_up_questions(
        self, *, question: str, answer: str, result: dict | None = None, model: str
    ) -> list[str]:
        data_context = ""
        if result and result.get("rows"):
            rows = result["rows"][:10]
            cols = result.get("columns", [])
            data_context = (
                f"\n\nActual data returned (columns: {cols}):\n"
                + "\n".join(str(r) for r in rows)
            )
        user = (
            f"User question: {question}\n\n"
            f"Answer summary: {answer[:400]}"
            f"{data_context}\n\n"
            "Generate 3 specific, self-contained follow-up questions using actual names/values from the data above."
        )
        resp = await self._client.messages.create(
            model=self._settings.claude_fast_model,
            max_tokens=300,
            system=_FOLLOWUP_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            text = text.strip()
            if text.startswith("```"):
                text = text.strip("`").lstrip("json").strip()
            start, end = text.index("["), text.rindex("]") + 1
            result = json.loads(text[start:end])
            if isinstance(result, list):
                return [str(q) for q in result[:3]]
        except (ValueError, json.JSONDecodeError):
            pass
        return []


def _safe_json(text: str, default: dict) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return default
