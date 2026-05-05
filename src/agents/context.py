"""Agent context builder — assembles structured evidence dicts for agents."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_REAL_TICKER_RE = re.compile(r'^[A-Z]{1,5}(\.[A-Z]+)?$')

ROOT = Path(__file__).resolve().parent.parent.parent
CONTEXT_CACHE_DIR = ROOT / "data" / "raw" / "agent_context"
CONTEXT_TTL = 4 * 3600

log = logging.getLogger("visionairy2.agents.context")


class AgentContextBuilder:
    def __init__(self, db_session_factory: Any = None, fetcher: Any = None) -> None:
        self._db = db_session_factory
        self._fetcher = fetcher

    # ── public API ──────────────────────────────────────────────────────────

    def build_for_ticker(
        self,
        ticker: str,
        sector_id: Optional[str] = None,
        lookback_days_quant: int = 7,
        lookback_days_qual: int = 14,
    ) -> dict[str, Any]:
        cache_key = hashlib.sha256(
            f"ticker:{ticker}:{sector_id}:{lookback_days_quant}:{lookback_days_qual}".encode()
        ).hexdigest()
        cached = self._load_context_cache(cache_key)
        if cached is not None:
            return cached

        from src.sources.registry import get_client
        from src.sources.base import SourceQuery
        from src.ingestion.deduper import Deduper

        completeness: dict[str, Any] = {}
        ctx: dict[str, Any] = {
            "ticker": ticker,
            "company_name": None,
            "sector_id": sector_id,
            "fundamentals": {},
            "price": {},
            "filings_recent": [],
            "news_recent": [],
            "insider_transactions": [],
            "research_papers": [],
            "patents": [],
            "gov_contracts": [],
            "fda_actions": [],
            "macro_indicators": {},
            "tech_signal": [],
            "data_completeness": completeness,
        }

        deduper = Deduper()

        # ── fundamentals ──────────────────────────────────────────────────
        for src_id in ["findata", "alpha_vantage"]:
            try:
                client = get_client(src_id, config=None, db_session_factory=self._db)
                if not client.is_available():
                    completeness[src_id] = "unavailable"
                    continue
                q = SourceQuery(ticker=ticker, limit=5)
                result = client.fetch(q)
                if result.documents:
                    ctx["fundamentals"] = result.documents[0].raw_payload
                    completeness[src_id] = f"{len(result.documents)} docs"
                    break
                else:
                    completeness[src_id] = "empty"
            except Exception as exc:
                completeness[src_id] = f"error: {exc}"

        # ── price ─────────────────────────────────────────────────────────
        if not _REAL_TICKER_RE.match(ticker):
            completeness["yfinance"] = "skipped: not_ticker_format"
        else:
            try:
                client = get_client("yfinance", config=None, db_session_factory=self._db)
                if client.is_available():
                    q = SourceQuery(ticker=ticker, limit=1)
                    result = client.fetch(q)
                    if result.documents:
                        ctx["price"] = result.documents[0].raw_payload
                        if not ctx["company_name"]:
                            ctx["company_name"] = result.documents[0].title
                    completeness["yfinance"] = "ok" if result.documents else "empty"
            except Exception as exc:
                completeness["yfinance"] = f"error: {exc}"

        # ── price history (1y daily for Plotly chart) ─────────────────────
        ctx["price_history"] = []
        if _REAL_TICKER_RE.match(ticker):
            try:
                import yfinance as yf
                t_obj = yf.Ticker(ticker)
                hist = t_obj.history(period="1y", interval="1d")
                ctx["price_history"] = [
                    {
                        "date": d.strftime("%Y-%m-%d"),
                        "open": round(float(o), 4),
                        "high": round(float(h), 4),
                        "low": round(float(l), 4),
                        "close": round(float(c), 4),
                        "volume": int(v),
                    }
                    for d, o, h, l, c, v in zip(
                        hist.index, hist["Open"], hist["High"],
                        hist["Low"], hist["Close"], hist["Volume"]
                    )
                ]
                completeness["price_history"] = f"{len(ctx['price_history'])} days"
            except Exception as exc:
                completeness["price_history"] = f"error: {exc}"
                ctx["price_history"] = []

        # ── SEC filings ───────────────────────────────────────────────────
        try:
            client = get_client("edgar", config=None, db_session_factory=self._db)
            if client.is_available():
                q = SourceQuery(ticker=ticker, limit=10, lookback_days=lookback_days_qual * 5,
                                extra={"mode": "recent_filings"})
                result = client.fetch(q)
                ctx["filings_recent"] = [_doc_to_dict(d) for d in result.documents[:10]]
                completeness["edgar"] = f"{len(result.documents)} filings"
            else:
                completeness["edgar"] = "unavailable"
        except Exception as exc:
            completeness["edgar"] = f"error: {exc}"

        # ── news ──────────────────────────────────────────────────────────
        all_news_docs = []
        for src_id in ["marketaux", "guardian", "finnhub", "newsapi", "newsdata"]:
            try:
                client = get_client(src_id, config=None, db_session_factory=self._db)
                if not client.is_available():
                    completeness[src_id] = "unavailable"
                    continue
                q = SourceQuery(ticker=ticker, query_string=ticker,
                                lookback_days=lookback_days_qual, limit=15)
                result = client.fetch(q)
                all_news_docs.extend(result.documents)
                completeness[src_id] = f"{len(result.documents)} docs"
            except Exception as exc:
                completeness[src_id] = f"error: {exc}"

        deduped_news = deduper.dedupe(all_news_docs)
        ctx["news_recent"] = [_doc_to_dict(d) for d in deduped_news[:30]]

        # ── insider transactions ───────────────────────────────────────────
        try:
            client = get_client("finnhub", config=None, db_session_factory=self._db)
            if client.is_available():
                q = SourceQuery(ticker=ticker, lookback_days=90, limit=20,
                                extra={"data_type": "insider"})
                result = client.fetch(q)
                ctx["insider_transactions"] = [_doc_to_dict(d) for d in result.documents]
                completeness["finnhub_insider"] = f"{len(result.documents)}"
        except Exception as exc:
            completeness["finnhub_insider"] = f"error: {exc}"

        # ── research papers ───────────────────────────────────────────────
        all_papers = []
        for src_id in ["arxiv", "openalex", "papers_with_code"]:
            try:
                client = get_client(src_id, config=None, db_session_factory=self._db)
                if not client.is_available():
                    completeness[src_id] = "unavailable"
                    continue
                company_name = ctx.get("company_name") or ticker
                keywords = _sector_keywords(sector_id)
                q = SourceQuery(query_string=keywords or company_name,
                                lookback_days=60, limit=10)
                result = client.fetch(q)
                all_papers.extend(result.documents)
                completeness[src_id] = f"{len(result.documents)} papers"
            except Exception as exc:
                completeness[src_id] = f"error: {exc}"

        ctx["research_papers"] = [_doc_to_dict(d) for d in all_papers[:10]]

        # ── gov contracts (defence/AI sectors) ───────────────────────────
        if sector_id in ("traditional_defence", "emerging_defence", "ai_chips_compute", "space_satellites"):
            try:
                client = get_client("usaspending", config=None, db_session_factory=self._db)
                if client.is_available():
                    q = SourceQuery(query_string=ctx.get("company_name") or ticker,
                                    lookback_days=90, limit=10)
                    result = client.fetch(q)
                    ctx["gov_contracts"] = [_doc_to_dict(d) for d in result.documents]
                    completeness["usaspending"] = f"{len(result.documents)}"
            except Exception as exc:
                completeness["usaspending"] = f"error: {exc}"

        # ── FDA actions (pharma sectors) ──────────────────────────────────
        if sector_id in ("pharma_glp1", "genetic_cell_therapy", "medtech_diagnostics"):
            try:
                client = get_client("openfda", config=None, db_session_factory=self._db)
                if client.is_available():
                    q = SourceQuery(query_string=ctx.get("company_name") or ticker,
                                    lookback_days=90, limit=10)
                    result = client.fetch(q)
                    ctx["fda_actions"] = [_doc_to_dict(d) for d in result.documents]
                    completeness["openfda"] = f"{len(result.documents)}"
            except Exception as exc:
                completeness["openfda"] = f"error: {exc}"

        # ── macro indicators ──────────────────────────────────────────────
        for src_id in ["fred", "eia"]:
            try:
                client = get_client(src_id, config=None, db_session_factory=self._db)
                if not client.is_available():
                    completeness[src_id] = "unavailable"
                    continue
                q = SourceQuery(sector_id=sector_id, limit=5)
                result = client.fetch(q)
                if result.documents:
                    ctx["macro_indicators"][src_id] = [_doc_to_dict(d) for d in result.documents]
                completeness[src_id] = f"{len(result.documents)}"
            except Exception as exc:
                completeness[src_id] = f"error: {exc}"

        # ── tech signals ──────────────────────────────────────────────────
        for src_id in ["github", "hackernews"]:
            try:
                client = get_client(src_id, config=None, db_session_factory=self._db)
                if not client.is_available():
                    completeness[src_id] = "unavailable"
                    continue
                q = SourceQuery(query_string=ctx.get("company_name") or ticker, limit=5)
                result = client.fetch(q)
                ctx["tech_signal"].extend([_doc_to_dict(d) for d in result.documents])
                completeness[src_id] = f"{len(result.documents)}"
            except Exception as exc:
                completeness[src_id] = f"error: {exc}"

        self._save_context_cache(cache_key, ctx)
        return ctx

    def build_for_document(self, url_or_path: str) -> dict[str, Any]:
        is_url = url_or_path.startswith("http://") or url_or_path.startswith("https://")
        ctx: dict[str, Any] = {
            "source_url": url_or_path if is_url else None,
            "source_path": url_or_path if not is_url else None,
            "raw_text": "",
            "extracted_entities": [],
            "title": "",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        raw_text = ""
        if not is_url:
            raw_text = self._read_local_file(url_or_path)
            ctx["title"] = Path(url_or_path).name
        else:
            raw_text = self._scrape_url(url_or_path)
            ctx["title"] = url_or_path

        ctx["raw_text"] = raw_text[:8000]

        if raw_text:
            try:
                from src.ingestion.extractor import EntityExtractor
                from src.llm.client import complete as _llm_complete
                _llm_shim = type("_LLM", (), {"complete": staticmethod(_llm_complete)})()
                extractor = EntityExtractor(llm_client=_llm_shim)
                entities = extractor.extract_companies(raw_text[:4000])
                ctx["extracted_entities"] = entities
            except Exception as exc:
                log.warning("Entity extraction failed: %s", exc)

        return ctx

    def build_for_discovery_scan(
        self,
        sectors_active: list[str],
        lookback_days: int,
    ) -> dict[str, Any]:
        from src.sources.base import SourceQuery
        from src.ingestion.fetcher import ParallelFetcher
        from src.ingestion.deduper import Deduper
        from src.ingestion.extractor import EntityExtractor
        from src.ingestion.ticker_resolver import TickerResolver

        from src.llm.client import complete as _llm_complete
        _llm_shim = type("_LLM", (), {"complete": staticmethod(_llm_complete)})()

        fetcher = self._fetcher or ParallelFetcher(config=None, db_session_factory=self._db)
        deduper = Deduper()
        extractor = EntityExtractor(llm_client=_llm_shim)
        resolver = TickerResolver(db_session_factory=self._db, llm_client=_llm_shim)

        from src.config import get_config
        from src.sources.registry import list_available_sources
        cfg = get_config()

        all_docs = []
        for sector_id in sectors_active:
            try:
                sector_cfg = next((s for s in cfg.sectors if s.id == sector_id), None)
                keywords = " ".join((sector_cfg.keywords or [])[:3]) if sector_cfg else sector_id
                q = SourceQuery(
                    query_string=keywords,
                    sector_id=sector_id,
                    lookback_days=lookback_days,
                    limit=20,
                )
                available_sources = list_available_sources(cfg)
                queries = [(src_id, q) for src_id in available_sources[:12]]
                results = fetcher.fetch_all(queries)
                for r in results:
                    all_docs.extend(r.documents)
            except Exception as exc:
                log.warning("Discovery fetch failed for %s: %s", sector_id, exc)

        deduped = deduper.dedupe(all_docs)

        entity_map: dict[str, list[str]] = {}
        try:
            enriched_docs = extractor.extract_from_documents(list(deduped))
            for doc in enriched_docs:
                for entity_name in (doc.entities_mentioned or []):
                    entity_map.setdefault(entity_name, []).append(doc.source_id)
        except Exception as exc:
            log.warning("Entity extraction failed: %s", exc)

        company_mentions: dict[str, list[str]] = {}
        for name, doc_ids in entity_map.items():
            try:
                ticker = resolver.resolve(name)
                if ticker:
                    company_mentions.setdefault(ticker, []).extend(doc_ids)
            except Exception:
                pass

        return {
            "scan_started_at": datetime.now(timezone.utc).isoformat(),
            "sectors": sectors_active,
            "lookback_days": lookback_days,
            "all_documents": [_doc_to_dict(d) for d in deduped],
            "company_mentions": company_mentions,
            "candidates": [],
        }

    # ── private helpers ──────────────────────────────────────────────────

    def _scrape_url(self, url: str) -> str:
        from src.sources.registry import get_client
        for src_id in ["firecrawl", "tavily"]:
            try:
                client = get_client(src_id, config=None, db_session_factory=None)
                if not client.is_available():
                    continue
                from src.sources.base import SourceQuery
                q = SourceQuery(query_string=url, extra={"url": url}, limit=1)
                result = client.fetch(q)
                if result.documents:
                    payload = result.documents[0].raw_payload
                    text = payload.get("markdown") or payload.get("content") or result.documents[0].summary or ""
                    if text:
                        return text
            except Exception as exc:
                log.warning("%s scrape failed: %s", src_id, exc)

        try:
            import httpx
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            from html.parser import HTMLParser
            class _Strip(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.parts: list[str] = []
                def handle_data(self, data):
                    self.parts.append(data)
            p = _Strip()
            p.feed(resp.text)
            return " ".join(p.parts)[:4000]
        except Exception as exc:
            log.warning("httpx fallback scrape failed: %s", exc)
        return ""

    def _read_local_file(self, path_str: str) -> str:
        p = Path(path_str)
        if not p.exists():
            return ""
        suffix = p.suffix.lower()
        if suffix in (".md", ".txt", ".html"):
            return p.read_text(errors="replace")[:8000]
        if suffix == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(p) as pdf:
                    pages = [page.extract_text() or "" for page in pdf.pages[:20]]
                return "\n".join(pages)[:8000]
            except ImportError:
                try:
                    import pypdf
                    reader = pypdf.PdfReader(str(p))
                    return "\n".join(page.extract_text() or "" for page in reader.pages[:20])[:8000]
                except Exception:
                    pass
        return p.read_text(errors="replace")[:8000]

    def _cache_path(self, key: str) -> Path:
        return CONTEXT_CACHE_DIR / f"{key}.json"

    def _load_context_cache(self, key: str) -> dict | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > CONTEXT_TTL:
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _save_context_cache(self, key: str, ctx: dict) -> None:
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(ctx, default=str))
        tmp.rename(path)


def _doc_to_dict(d: Any) -> dict[str, Any]:
    return {
        "source": d.source,
        "source_id": d.source_id,
        "url": d.url,
        "doc_type": d.doc_type,
        "title": d.title,
        "published_at": d.published_at.isoformat() if d.published_at else None,
        "summary": d.summary,
        "raw_payload": d.raw_payload,
    }


def _sector_keywords(sector_id: str | None) -> str:
    if not sector_id:
        return ""
    try:
        from src.config import get_config
        cfg = get_config()
        sector = next((s for s in cfg.sectors if s.id == sector_id), None)
        if sector and sector.keywords:
            return " ".join(sector.keywords[:4])
    except Exception:
        pass
    return sector_id.replace("_", " ")
