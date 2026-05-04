"""Typed configuration loader.

Combines values from .env (via pydantic-settings) and config.yaml (sectors,
watchlist, discovery, llm_routing). Single entry point: get_config().
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
CONFIG_YAML_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"


class Secrets(BaseSettings):
    """Loaded from .env."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # LLM providers
    ANTHROPIC_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # SEC EDGAR
    SEC_USER_AGENT: str = "VisionAiry2 projectgemini53@gmail.com"

    # Financial
    FINANCIAL_DATASETS_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""
    FMP_API_KEY: str = ""
    ALPHA_VANTAGE_API_KEY: str = ""

    # News
    GUARDIAN_API_KEY: str = ""
    MARKETAUX_API_KEY: str = ""
    NEWSAPI_KEY: str = ""
    NEWSDATA_API_KEY: str = ""

    # Research / academic
    SEMANTIC_SCHOLAR_API_KEY: str = ""
    CORE_API_KEY: str = ""
    NCBI_API_KEY: str = ""

    # Specialist
    OPENFDA_API_KEY: str = ""
    USPTO_API_KEY: str = ""
    EIA_API_KEY: str = ""
    SAM_GOV_API_KEY: str = ""

    # Tech / macro / search
    GITHUB_TOKEN: str = ""
    FRED_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    FIRECRAWL_API_KEY: str = ""
    EXA_API_KEY: str = ""
    SERPER_API_KEY: str = ""
    STOCKTWITS_API_KEY: str = ""

    # Runtime
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: str = "sqlite:///data/state.db"


class RoleRouting(BaseModel):
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None
    max_tokens: int = 2048
    temperature: float = 0.3


class WatchlistEntry(BaseModel):
    ticker: str
    tier: str = "C"


class DiscoveryConfig(BaseModel):
    trigger: str = "manual"
    lookback_window: dict[str, int]
    scope: dict[str, Any]
    top_n: int = 7
    report_depth: str = "medium"
    personas_per_candidate: list[str]
    estimated_cost_per_scan_usd: list[float]


class SectorConfig(BaseModel):
    id: str
    label: str
    keywords: list[str]
    arxiv_categories: list[str] = Field(default_factory=list)
    specialist_sources: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    secrets: Secrets
    sectors: list[SectorConfig]
    watchlist: dict[str, list[WatchlistEntry]]
    discovery: DiscoveryConfig
    llm_routing: dict[str, RoleRouting]

    def role(self, name: str) -> RoleRouting:
        if name not in self.llm_routing:
            raise KeyError(f"Unknown llm_routing role: {name}")
        return self.llm_routing[name]

    def sector(self, sid: str) -> SectorConfig:
        for s in self.sectors:
            if s.id == sid:
                return s
        raise KeyError(f"Unknown sector_id: {sid}")


def _load_yaml() -> dict[str, Any]:
    with CONFIG_YAML_PATH.open() as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    raw = _load_yaml()
    return AppConfig(
        secrets=Secrets(),
        sectors=[SectorConfig(**s) for s in raw.get("sectors", [])],
        watchlist={
            sid: [WatchlistEntry(**e) for e in entries]
            for sid, entries in (raw.get("watchlist") or {}).items()
        },
        discovery=DiscoveryConfig(**raw["discovery"]),
        llm_routing={k: RoleRouting(**v) for k, v in raw["llm_routing"].items()},
    )


def reload_config() -> AppConfig:
    """Force re-read from disk (e.g. after validate-keys rewrites config.yaml)."""
    get_config.cache_clear()
    return get_config()
