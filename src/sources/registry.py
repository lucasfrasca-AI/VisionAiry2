"""Source client registry — singleton instances by source_id."""

from __future__ import annotations

from typing import Any, Optional

# Populated at bottom of this file once all client modules are imported
SOURCE_REGISTRY: dict[str, type] = {}
_instances: dict[str, Any] = {}


def _register_all() -> None:
    """Import all client modules to populate SOURCE_REGISTRY."""
    from src.sources.finnhub import FinnhubClient
    from src.sources.fmp import FMPClient
    from src.sources.findata import FinancialDatasetsClient
    from src.sources.alpha_vantage import AlphaVantageClient
    from src.sources.edgar import EdgarClient
    from src.sources.marketaux import MarketauxClient
    from src.sources.guardian import GuardianClient
    from src.sources.newsapi import NewsAPIClient
    from src.sources.newsdata import NewsdataClient
    from src.sources.fred import FredClient
    from src.sources.eia import EiaClient
    from src.sources.openfda import OpenFdaClient
    from src.sources.github import GithubClient
    from src.sources.tavily import TavilyClient
    from src.sources.firecrawl import FirecrawlClient
    from src.sources.yfinance_client import YfinanceClient
    from src.sources.arxiv import ArxivClient
    from src.sources.biorxiv import BiorxivClient
    from src.sources.openalex import OpenAlexClient
    from src.sources.crossref import CrossrefClient
    from src.sources.usaspending import USASpendingClient
    from src.sources.clinicaltrials import ClinicalTrialsClient
    from src.sources.gdelt import GdeltClient
    from src.sources.hackernews import HackerNewsClient
    from src.sources.papers_with_code import PapersWithCodeClient
    from src.sources.wikidata import WikidataClient
    from src.sources.world_bank import WorldBankClient

    for cls in [
        FinnhubClient, FMPClient, FinancialDatasetsClient, AlphaVantageClient,
        EdgarClient, MarketauxClient, GuardianClient, NewsAPIClient, NewsdataClient,
        FredClient, EiaClient, OpenFdaClient, GithubClient, TavilyClient,
        FirecrawlClient, YfinanceClient, ArxivClient, BiorxivClient, OpenAlexClient,
        CrossrefClient, USASpendingClient, ClinicalTrialsClient, GdeltClient,
        HackerNewsClient, PapersWithCodeClient, WikidataClient, WorldBankClient,
    ]:
        SOURCE_REGISTRY[cls.source_id] = cls


def get_client(source_id: str, config: Any, db_session_factory: Any = None) -> Any:
    """Return singleton client instance for source_id."""
    if not SOURCE_REGISTRY:
        _register_all()
    if source_id not in _instances:
        cls = SOURCE_REGISTRY.get(source_id)
        if cls is None:
            raise KeyError(f"Unknown source_id: {source_id!r}")
        _instances[source_id] = cls(config, db_session_factory)
    return _instances[source_id]


def list_available_sources(config: Any) -> list[str]:
    if not SOURCE_REGISTRY:
        _register_all()
    return [sid for sid, cls in SOURCE_REGISTRY.items() if cls(config).is_available()]


def list_disabled_sources(config: Any) -> list[tuple[str, str]]:
    if not SOURCE_REGISTRY:
        _register_all()
    out = []
    for sid, cls in SOURCE_REGISTRY.items():
        inst = cls(config)
        if not inst.is_available():
            reason = f"key {inst.key_env_var} not set or invalid" if inst.needs_key else "unavailable"
            out.append((sid, reason))
    return out


def get_sources_by_doc_type(doc_type: str) -> list[str]:
    if not SOURCE_REGISTRY:
        _register_all()
    results = []
    for sid, cls in SOURCE_REGISTRY.items():
        inst_doc_types = getattr(cls, "doc_types", [])
        primary_doc_type = getattr(cls, "primary_doc_type", None)
        if doc_type in inst_doc_types or doc_type == primary_doc_type:
            results.append(sid)
    return results


def get_sources_by_sector(sector_id: str, config: Any) -> list[str]:
    if not SOURCE_REGISTRY:
        _register_all()
    return [
        sid for sid, cls in SOURCE_REGISTRY.items()
        if cls.sector_routed and cls(config).is_available()
    ]


def reset_instances() -> None:
    """Clear singleton cache (useful in tests)."""
    _instances.clear()
