-- SAP B1 MVP — PostgreSQL schema (catalog + knowledge graph + sessions + embeddings)
-- Requires the pgvector extension (shipped in the pgvector/pgvector image).

CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────────────────────────────────────
-- Metadata catalog
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS catalog_tables (
    table_name      TEXT PRIMARY KEY,
    module          TEXT,
    module_id       INT,
    description     TEXT,
    is_master       BOOLEAN NOT NULL DEFAULT FALSE,
    is_core_domain  BOOLEAN NOT NULL DEFAULT FALSE,
    total_columns   INT NOT NULL DEFAULT 0,
    primary_key     TEXT[] NOT NULL DEFAULT '{}',
    pk_confidence   REAL NOT NULL DEFAULT 0,
    pk_rule         TEXT
);

CREATE INDEX IF NOT EXISTS ix_catalog_tables_module      ON catalog_tables (module);
CREATE INDEX IF NOT EXISTS ix_catalog_tables_core        ON catalog_tables (is_core_domain);

CREATE TABLE IF NOT EXISTS catalog_columns (
    id              BIGSERIAL PRIMARY KEY,
    table_name      TEXT NOT NULL REFERENCES catalog_tables(table_name) ON DELETE CASCADE,
    column_number   INT NOT NULL,
    field           TEXT NOT NULL,
    description     TEXT,
    type            TEXT,
    length          INT,
    UNIQUE (table_name, field)
);

CREATE INDEX IF NOT EXISTS ix_catalog_columns_table      ON catalog_columns (table_name);
CREATE INDEX IF NOT EXISTS ix_catalog_columns_field      ON catalog_columns (field);

-- ─────────────────────────────────────────────────────────────────────────────
-- Knowledge graph: derived join edges (foreign-key relationships)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_joins (
    id              BIGSERIAL PRIMARY KEY,
    from_table      TEXT NOT NULL,
    from_col        TEXT NOT NULL,
    to_table        TEXT NOT NULL,
    to_col          TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 0,
    rule            TEXT,
    UNIQUE (from_table, from_col, to_table, to_col)
);

CREATE INDEX IF NOT EXISTS ix_schema_joins_from          ON schema_joins (from_table);
CREATE INDEX IF NOT EXISTS ix_schema_joins_to            ON schema_joins (to_table);

-- ─────────────────────────────────────────────────────────────────────────────
-- Vector embeddings for retrieval. The vector dimension is substituted from
-- EMBED_DIM at apply time (Voyage voyage-3 = 1024, voyage-3-lite = 512).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_embeddings (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL,              -- 'table' | 'column'
    table_name      TEXT NOT NULL,
    field           TEXT NOT NULL DEFAULT '',   -- '' for table-level rows (NOT NULL so
                                                -- the UNIQUE/ON CONFLICT below works)
    content         TEXT NOT NULL,              -- the text that was embedded
    embedding       vector({{EMBED_DIM}}) NOT NULL,
    UNIQUE (kind, table_name, field)
);

CREATE INDEX IF NOT EXISTS ix_schema_embeddings_hnsw
    ON schema_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);

-- ─────────────────────────────────────────────────────────────────────────────
-- Conversation sessions (short-term memory) + turns
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS turns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,              -- 'user' | 'assistant'
    question        TEXT,
    thinking        TEXT,
    sql             TEXT,
    answer          TEXT,
    result_json     JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_turns_session             ON turns (session_id, created_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- RAG document store (uploaded files)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rag_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        TEXT NOT NULL,
    file_type       TEXT NOT NULL,              -- 'pdf' | 'docx' | 'xlsx' | 'txt'
    file_size       INT NOT NULL DEFAULT 0,
    chunk_count     INT NOT NULL DEFAULT 0,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id              BIGSERIAL PRIMARY KEY,
    doc_id          UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    chunk_index     INT NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector({{EMBED_DIM}}),
    UNIQUE (doc_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS ix_rag_chunks_doc            ON rag_chunks (doc_id);
CREATE INDEX IF NOT EXISTS ix_rag_chunks_hnsw
    ON rag_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128)
    WHERE embedding IS NOT NULL;
