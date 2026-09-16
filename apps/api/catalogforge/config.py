from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = (
        "postgresql+psycopg://catalogforge:catalogforge-local@localhost:5488/catalogforge"
    )
    storage_root: Path = Path("data/uploads")
    ai_mode: Literal["fixture", "real"] = "fixture"
    openai_api_key: SecretStr = SecretStr("")
    chat_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = Field(default=1536, ge=64, le=3072)
    cookie_secure: bool = False
    web_origin: str = "http://localhost:5288"
    trusted_hosts: list[str] = ["localhost", "127.0.0.1"]
    demo_password: str = "CatalogForge-demo-2026!"
    max_upload_bytes: int = 20 * 1024 * 1024
    max_retrieval_rounds: int = Field(default=2, ge=1, le=3)
    max_run_seconds: int = Field(default=180, ge=10, le=600)
    worker_concurrency: int = Field(default=2, ge=1, le=8)

    ai_max_input_tokens: int = Field(default=32000, ge=1000, le=100000)
    ai_max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    ai_provider_retries: int = Field(default=1, ge=0, le=2)
    ai_call_timeout_seconds: int = Field(default=40, ge=1, le=90)
    ai_scope_max_calls: int = Field(default=200, ge=1, le=10000)
    ai_scope_max_tokens: int = Field(default=500000, ge=1)
    ai_workspace_max_calls: int = Field(default=1000, ge=1, le=100000)
    ai_workspace_max_tokens: int = Field(default=2000000, ge=1)
    ai_scope_budget_usd: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    ai_workspace_budget_usd: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    ai_chat_input_usd_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    ai_chat_output_usd_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    ai_embedding_usd_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    ai_pricing_date: str = ""
    ai_pricing_chat_model: str = ""
    ai_pricing_embedding_model: str = ""

    @model_validator(mode="after")
    def check_pricing(self):
        rates = [
            self.ai_chat_input_usd_per_million,
            self.ai_chat_output_usd_per_million,
            self.ai_embedding_usd_per_million,
        ]
        required = (
            any(rate is not None for rate in rates)
            or self.ai_scope_budget_usd is not None
            or self.ai_workspace_budget_usd is not None
        )
        if required:
            if any(rate is None for rate in rates):
                raise ValueError("Configure all three token prices before enabling USD budgets")
            date.fromisoformat(self.ai_pricing_date)
            if (
                self.ai_pricing_chat_model != self.chat_model
                or self.ai_pricing_embedding_model != self.embedding_model
            ):
                raise ValueError(
                    "Pricing must explicitly match the configured chat and embedding models"
                )
        return self

    @property
    def pg_url(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")

    @property
    def embedding_space(self) -> str:
        if self.ai_mode == "fixture":
            return "fixture:hash-v1:64"
        return f"real:{self.embedding_model}:{self.embedding_dimension}"


@lru_cache
def settings() -> Settings:
    return Settings()
