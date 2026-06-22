"""
Embedding provider abstraction.

Default = Voyage AI (free tier), called over HTTP via httpx — no heavy local deps.
Swap EMBED_PROVIDER in .env to "openai" or "local" without touching call sites.

    provider = get_provider(get_settings())
    vectors  = await provider.embed_documents(["TABLE OINV …", "TABLE OCRD …"])
    qvec     = await provider.embed_query("top customers by revenue")
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

import httpx

from app.config import Settings


@runtime_checkable
class EmbeddingProvider(Protocol):
    dim: int
    model: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


# ─────────────────────────────────────────────────────────────────────────────
# Voyage AI
# ─────────────────────────────────────────────────────────────────────────────
class VoyageProvider:
    """https://docs.voyageai.com/reference/embeddings-api"""

    BASE_URL = "https://api.voyageai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str = "voyage-3", dim: int = 1024, batch_size: int = 128):
        if not api_key:
            raise ValueError(
                "VOYAGE_API_KEY is required for EMBED_PROVIDER=voyage. "
                "Get a free key at https://dash.voyageai.com"
            )
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.batch_size = batch_size

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                out.extend(await self._post_with_retry(client, batch, input_type))
        return out

    async def _post_with_retry(
        self, client: httpx.AsyncClient, batch: list[str], input_type: str
    ) -> list[list[float]]:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await client.post(
                    self.BASE_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"input": batch, "model": self.model, "input_type": input_type},
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    resp.raise_for_status()  # trigger retry
                resp.raise_for_status()
                data = resp.json()["data"]
                # preserve input order via the per-item index
                data.sort(key=lambda d: d.get("index", 0))
                return [d["embedding"] for d in data]
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt == 2:
                    break
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"Voyage embedding failed after retries: {last_exc}")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, "document")

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "query"))[0]


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI (optional)
# ─────────────────────────────────────────────────────────────────────────────
class OpenAIProvider:
    BASE_URL = "https://api.openai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dim: int = 1536, batch_size: int = 128):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for EMBED_PROVIDER=openai")
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.batch_size = batch_size

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                resp = await client.post(
                    self.BASE_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"input": batch, "model": self.model},
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                data.sort(key=lambda d: d.get("index", 0))
                out.extend(d["embedding"] for d in data)
        return out

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]


# ─────────────────────────────────────────────────────────────────────────────
# Local sentence-transformers (optional, heavy — lazy import)
# ─────────────────────────────────────────────────────────────────────────────
class LocalProvider:
    def __init__(self, model: str = "all-MiniLM-L6-v2", dim: int = 384):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "EMBED_PROVIDER=local needs `pip install sentence-transformers`"
            ) from exc
        self._model = SentenceTransformer(model)
        self.model = model
        self.dim = dim

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # sentence-transformers is sync/CPU — run off the event loop
        return await asyncio.to_thread(
            lambda: self._model.encode(texts, normalize_embeddings=True).tolist()
        )

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


def get_provider(settings: Settings) -> EmbeddingProvider:
    p = settings.embed_provider.lower()
    if p == "voyage":
        return VoyageProvider(
            settings.voyage_api_key, settings.embed_model, settings.embed_dim, settings.embed_batch_size
        )
    if p == "openai":
        return OpenAIProvider(
            settings.openai_api_key, settings.embed_model, settings.embed_dim, settings.embed_batch_size
        )
    if p == "local":
        return LocalProvider(settings.embed_model, settings.embed_dim)
    raise ValueError(f"Unknown EMBED_PROVIDER: {settings.embed_provider}")
