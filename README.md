# SAP B1 AI Agent — Alex

A conversational AI analytics assistant for **SAP Business One (SAP HANA)**. Ask business questions in plain English and receive SQL-backed answers, charts, and insights — no SQL knowledge required.

---

## What it does

- Accepts natural language questions about SAP B1 data (sales, purchases, inventory, customers, vendors, payments)
- Generates valid SAP HANA SQL using Claude (Sonnet or Opus)
- Executes the SQL via the SAP B1 Service Layer HTTP endpoint
- Returns structured answers with auto-selected visualisations (KPI card / bar chart / line chart / table)
- Streams reasoning, SQL, and the final answer in real time
- Maintains conversation history per session
- Supports RAG — upload documents (PDF, DOCX, TXT) and the agent uses them to supplement answers
- Exposes SAP B1 CRUD APIs (create/update/delete sales orders, purchase orders, etc.)
- Multi-stage SQL retry logic — automatically detects and fixes invalid patterns (CURRENT_DATE, UNION ALL, FROM subqueries)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.12, asyncpg |
| AI | Anthropic Claude API (Sonnet 4.6 / Opus 4.8 / Haiku 4.5) |
| Vector Search | pgvector (PostgreSQL 16) or Supabase (pgvector hosted) |
| Embeddings | Voyage AI (`voyage-3`, 1024-dim) |
| SQL Validation | sqlglot |
| Document Store | RAG pipeline (PDF / DOCX / TXT upload → chunked embeddings) |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Recharts |
| State | Zustand |
| Infrastructure | Docker Compose |

---

## Architecture

```
User Question
  → Intent + keyword extraction    (Claude Haiku — fast)
  → Vector retrieval               (pgvector — top relevant SAP B1 tables)
  → Join-path lookup               (Knowledge Graph in PostgreSQL)
  → SQL generation                 (Claude Sonnet/Opus + extended thinking)
  → SQL validation                 (sqlglot — blocks all DML)
  → Execute via SAP B1 Service Layer  (HTTP GET ?query=<sql>)
  → Result type detection          (KPI / bar / line / forecast / table)
  → Natural language summary       (Claude Sonnet — streamed via SSE)
  → Follow-up suggestions          (Claude Haiku)
```

---

## Prerequisites

- Python 3.12
- Node.js 20+
- Docker Desktop (for PostgreSQL + pgvector) **or** a Supabase project (hosted pgvector)
- [Anthropic API key](https://console.anthropic.com)
- [Voyage AI API key](https://dash.voyageai.com) (free tier)
- Access to a SAP B1 Service Layer HTTP endpoint
- SAP B1 schema reference file: `erpref_cleaned_database.json`

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/menem-developers/sapb1_ai.git
cd sapb1_ai
```

### 2. Start PostgreSQL + pgvector

**Option A — Docker (local):**
```bash
docker compose up -d
```
This starts a PostgreSQL 16 instance with pgvector on port `5432`.

**Option B — Supabase (hosted):**
Create a Supabase project and enable the `pgvector` extension. Set `PG_DSN` in `.env` to your Supabase connection string (Transaction pooler recommended). The schema in `backend/sql/schema.sql` is Supabase-compatible and will be applied on first startup if the file is present.

### 3. Backend setup

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Activate (Mac/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env      # Windows
cp .env.example .env        # Mac/Linux
```

Edit `.env` and fill in:
- `ANTHROPIC_API_KEY` — your Anthropic API key
- `VOYAGE_API_KEY` — your Voyage AI API key
- `SERVICE_LAYER_URL` — your SAP B1 service layer endpoint
- `PG_DSN` — PostgreSQL connection string (local Docker or Supabase)

### 4. Build the catalog (one-time, offline)

This reads the SAP B1 schema reference JSON and builds the metadata catalog, knowledge graph, and vector embeddings.

```bash
# Build catalog + knowledge graph from SAP B1 schema reference
python scripts/build_catalog.py --input "path/to/erpref_cleaned_database.json" --load-db

# Generate tool templates + example questions
python scripts/build_tools.py --out output

# Embed catalog into pgvector (requires VOYAGE_API_KEY)
python scripts/build_embeddings.py
```

> This step only needs to be run once. Re-run only if the SAP B1 schema reference is updated.

### 5. Start the backend

```bash
uvicorn app.main:app --reload --port 8000
```

API will be available at `http://localhost:8000`.

### 6. Start the frontend

```bash
cd ../frontend

npm install
npm run dev
```

Frontend will be available at `http://localhost:5173`.

### 7. Login

Default credentials (configurable in `.env`):
- **Username:** `admin`
- **Password:** `demo`

---

## Environment Variables

All variables are set in `backend/.env`. See `backend/.env.example` for the full template.

| Variable | Description | Required |
|---|---|---|
| `PG_DSN` | PostgreSQL connection string | Yes |
| `ANTHROPIC_API_KEY` | Anthropic API key | Yes |
| `VOYAGE_API_KEY` | Voyage AI embedding key | Yes |
| `SERVICE_LAYER_URL` | SAP B1 service layer HTTP endpoint | Yes |
| `CLAUDE_DEFAULT_MODEL` | Default Claude model (Sonnet) | No |
| `CLAUDE_OPUS_MODEL` | Premium Claude model (Opus) | No |
| `CLAUDE_FAST_MODEL` | Fast Claude model (Haiku) | No |
| `EMBED_PROVIDER` | Embedding provider: `voyage` / `openai` / `local` | No |
| `EMBED_MODEL` | Embedding model name | No |
| `EMBED_DIM` | Embedding dimension (must match pgvector schema) | No |
| `SERVICE_LAYER_TIMEOUT` | HTTP timeout in seconds (default: 30) | No |
| `SERVICE_LAYER_ROW_CAP` | Max rows returned per query (default: 1000) | No |
| `DEMO_USERNAME` | Login username | No |
| `DEMO_PASSWORD` | Login password | No |
| `SAP_B1_BASE_URL` | SAP B1 base URL for CRUD operations | No |
| `SAP_B1_COMPANY_DB` | SAP B1 company database name | No |
| `SAP_B1_USERNAME` | SAP B1 username for CRUD operations | No |
| `SAP_B1_PASSWORD` | SAP B1 password for CRUD operations | No |

---

## SAP B1 Service Layer

The agent executes SQL through an HTTP endpoint — not a direct database connection:

```
GET {SERVICE_LAYER_URL}?query={url-encoded HANA SQL}

Success → 200, JSON array:  [{"CardName": "...", "DocTotal": 12345.6}, ...]
Error   → non-200, JSON:    {"status": 403, "message": "sql syntax error: ..."}
```

All generated SQL is in **SAP HANA dialect**:
- Double-quoted identifiers: `"OINV"`, `"CardCode"`
- `LIMIT` (not `TOP`)
- `ADD_MONTHS()`, `TO_VARCHAR()` date functions (not `DATEADD`, `FORMAT`)
- `CAST(... AS DOUBLE)` for all money/decimal columns

---

## Features

- **Dual model toggle** — Switch between Sonnet (fast) and Opus (complex queries) in the UI header
- **Extended thinking** — Claude's reasoning is shown in a collapsible panel
- **Auto visualisation** — Results render as KPI card, bar chart, line chart, or table automatically
- **Conversation memory** — Full session history with sidebar navigation
- **Follow-up suggestions** — 3 contextual follow-up questions generated after every answer
- **SQL transparency** — Generated SQL is always visible and copyable
- **Multi-stage retry logic** — Detects CURRENT_DATE (returns 0 rows on historical data), UNION ALL, and FROM subquery patterns; retries up to 3 times with progressively stronger instructions
- **RAG document upload** — Upload PDFs, DOCXs, or TXT files; the agent chunks, embeds, and retrieves relevant sections to supplement SQL answers
- **SAP B1 CRUD APIs** — Create, update, and delete SAP B1 documents (sales orders, purchase orders, etc.) via the service layer
- **Supabase-compatible** — Works with both local Docker PostgreSQL and hosted Supabase (pgvector)

---

## Project Structure

```
sapb1_ai/
├── backend/
│   ├── app/
│   │   ├── main.py                  FastAPI app entry point
│   │   ├── config.py                Settings from .env
│   │   ├── db.py                    PostgreSQL connection pool
│   │   ├── api/
│   │   │   └── routes.py            API endpoints (SSE chat, sessions, schema)
│   │   ├── chat/
│   │   │   ├── pipeline.py          Main question → answer pipeline (multi-stage SQL retry)
│   │   │   ├── claude.py            Claude API client + all system prompts
│   │   │   ├── memory.py            Session + turn persistence
│   │   │   ├── service_layer.py     SAP B1 HTTP query execution
│   │   │   ├── sql_validator.py     SQL validation + sanitization
│   │   │   ├── sap_actions.py       SAP B1 CRUD operations (create/update/delete)
│   │   │   ├── result_types.py      Chart type detection
│   │   │   └── forecast.py          Linear forecast calculation
│   │   ├── rag/
│   │   │   └── document_store.py    RAG document chunking, embedding + retrieval
│   │   ├── ingestion/
│   │   │   ├── loader.py            SAP B1 schema JSON loader
│   │   │   ├── pk_resolver.py       Primary key derivation
│   │   │   ├── fk_resolver.py       Foreign key / join derivation
│   │   │   └── catalog_builder.py   Catalog + KG builder
│   │   ├── semantic/
│   │   │   └── builder.py           Business entity semantic layer
│   │   ├── tools/
│   │   │   └── generator.py         Query tool templates + example questions
│   │   ├── embeddings/
│   │   │   └── provider.py          Voyage / OpenAI / local embedding provider
│   │   └── retrieval/
│   │       └── retriever.py         pgvector similarity search
│   ├── scripts/
│   │   ├── build_catalog.py         One-time catalog + KG build script
│   │   ├── build_tools.py           Tool template generation script
│   │   └── build_embeddings.py      pgvector embedding script
│   ├── sql/
│   │   └── schema.sql               PostgreSQL schema DDL
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatScreen.tsx       Main chat interface
│   │   │   ├── ResultView.tsx       Chart + table result renderer
│   │   │   ├── Charts.tsx           Bar, Line, Forecast, KPI chart components
│   │   │   ├── ThinkingPanel.tsx    Claude reasoning display
│   │   │   ├── SqlPanel.tsx         Generated SQL display
│   │   │   ├── Sidebar.tsx          Session history sidebar
│   │   │   └── MessageInput.tsx     Question input box
│   │   ├── api.ts                   Backend SSE client
│   │   ├── store.ts                 Zustand state (model, thinking toggle)
│   │   └── types.ts                 TypeScript interfaces
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
└── README.md
```

---

## License

Private — Techative Pvt Ltd. All rights reserved.
