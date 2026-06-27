"""
RAG Document Store — upload, parse, chunk, embed, and store documents.

Supported formats: PDF, DOCX, XLSX, TXT
Each document is split into ~500-token chunks, embedded, and stored in rag_chunks
with a pgvector embedding for semantic search at query time.
"""

from __future__ import annotations

import io
import uuid

import asyncpg

from app.embeddings.provider import EmbeddingProvider


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="ignore")


def _extract_pdf(data: bytes) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        raise RuntimeError("pypdf is not installed. Run: pip install pypdf")


def _extract_docx(data: bytes) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx")


def _extract_xlsx(data: bytes) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        lines = []
        for sheet in wb.worksheets:
            lines.append(f"[Sheet: {sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                row_text = " | ".join(str(c) for c in row if c is not None)
                if row_text.strip():
                    lines.append(row_text)
        return "\n".join(lines)
    except ImportError:
        raise RuntimeError("openpyxl is not installed. Run: pip install openpyxl")


def extract_text(filename: str, data: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return _extract_pdf(data)
    if ext in ("docx", "doc"):
        return _extract_docx(data)
    if ext in ("xlsx", "xls"):
        return _extract_xlsx(data)
    return _extract_txt(data)


def file_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    mapping = {"pdf": "pdf", "docx": "docx", "doc": "docx",
               "xlsx": "xlsx", "xls": "xlsx", "txt": "txt", "csv": "txt"}
    return mapping.get(ext, "txt")


# ── Chunking ──────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping word chunks (~500 words each)."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk.strip())
        i += chunk_size - overlap
    return chunks


# ── Store operations ──────────────────────────────────────────────────────────

async def upload_document(
    pool: asyncpg.Pool,
    provider: EmbeddingProvider,
    filename: str,
    data: bytes,
) -> dict:
    """
    Parse, chunk, embed, and store a document.
    Returns the saved document metadata.
    """
    text = extract_text(filename, data)
    if not text.strip():
        raise ValueError("Could not extract any text from this file.")

    chunks = _chunk_text(text)
    if not chunks:
        raise ValueError("Document appears to be empty after text extraction.")

    # Embed all chunks in one batch
    embeddings = await provider.embed_documents(chunks)

    doc_id = str(uuid.uuid4())
    ftype = file_type(filename)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO rag_documents (id, filename, file_type, file_size, chunk_count)
                VALUES ($1, $2, $3, $4, $5)
                """,
                doc_id, filename, ftype, len(data), len(chunks),
            )
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                emb_str = "[" + ",".join(str(x) for x in emb) + "]"
                await conn.execute(
                    """
                    INSERT INTO rag_chunks (doc_id, chunk_index, content, embedding)
                    VALUES ($1, $2, $3, $4::vector)
                    """,
                    doc_id, i, chunk, emb_str,
                )

    return {
        "id": doc_id,
        "filename": filename,
        "file_type": ftype,
        "file_size": len(data),
        "chunk_count": len(chunks),
    }


async def list_documents(pool: asyncpg.Pool) -> list[dict]:
    """Return all uploaded documents."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, filename, file_type, file_size, chunk_count, uploaded_at "
            "FROM rag_documents ORDER BY uploaded_at DESC"
        )
    return [dict(r) for r in rows]


async def delete_document(pool: asyncpg.Pool, doc_id: str) -> bool:
    """Delete a document and all its chunks."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM rag_documents WHERE id = $1", doc_id
        )
    return result != "DELETE 0"


async def search_documents(
    pool: asyncpg.Pool,
    provider: EmbeddingProvider,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Semantic search across all uploaded document chunks.
    Returns top_k most relevant chunks with their source document name.
    """
    if not query.strip():
        return []

    # Skip embedding call if no documents have been uploaded yet
    async with pool.acquire() as conn:
        doc_count = await conn.fetchval("SELECT COUNT(*) FROM rag_documents")
    if not doc_count:
        return []

    query_emb = await provider.embed_query(query)
    # Convert float list to pgvector string format: '[0.1,0.2,...]'
    emb_str = "[" + ",".join(str(x) for x in query_emb) + "]"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.content, c.chunk_index, d.filename, d.file_type,
                   1 - (c.embedding <=> $1::vector) AS score
            FROM rag_chunks c
            JOIN rag_documents d ON c.doc_id = d.id
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
            """,
            emb_str, top_k,
        )
    return [dict(r) for r in rows if r["score"] > 0.3]
