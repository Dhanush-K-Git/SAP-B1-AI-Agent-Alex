"""Application settings (loaded from .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # ── PostgreSQL (catalog + KG + sessions + embeddings) ────────────────────
    pg_dsn: str = "postgresql://mvp:mvp@localhost:5432/sapb1_mvp"

    # ── Claude ───────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    claude_default_model: str = "claude-sonnet-4-6"
    claude_opus_model: str = "claude-opus-4-8"
    claude_fast_model: str = "claude-haiku-4-5-20251001"

    # ── Embeddings ───────────────────────────────────────────────────────────
    # provider: "voyage" (free tier) | "openai" | "local" (sentence-transformers)
    embed_provider: str = "voyage"
    embed_model: str = "voyage-3"            # 1024 dims; voyage-3-lite = 512 dims
    embed_dim: int = 1024                    # MUST match vector(N); apply_schema substitutes
    embed_batch_size: int = 128              # Voyage max batch
    voyage_api_key: str = ""
    openai_api_key: str = ""

    # ── SAP B1 Service Layer (HANA SQL execution over HTTP) ──────────────────
    # GET {url}?query={sql} → JSON array of row objects. Errors: {"status","message"}.
    service_layer_url: str = "http://vzone.in:1662/api/GetMethod/GetData"
    service_layer_timeout: float = 30.0
    service_layer_row_cap: int = 1000

    # ── Web search (optional, for forecast/benchmark context) ────────────────
    tavily_api_key: str = ""

    # SAP B1 Service Layer — transactional (create/update/cancel/close)
    # Standard SAP B1 SL REST API. Leave blank to disable CRUD endpoints.
    sap_sl_base_url: str = "https://vzone.in:50000/b1s/v2"  # SAP B1 Service Layer for CRUD
    sap_sl_company: str = ""        # CompanyDB name
    sap_sl_username: str = ""       # SAP B1 username
    sap_sl_password: str = ""       # SAP B1 password

    # ── Demo auth (hardcoded login) ──────────────────────────────────────────
    demo_username: str = "admin"
    demo_password: str = "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
