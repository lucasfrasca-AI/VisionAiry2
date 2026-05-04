from __future__ import annotations
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from typing import Any

from src.sources.base import SourceQuery, SourceResult
from src.sources.registry import get_client, list_available_sources

logger = logging.getLogger("visionairy2.ingestion.fetcher")


class ParallelFetcher:
    def __init__(self, config: Any, registry: Any = None, db_session_factory: Any = None) -> None:
        self._config = config
        self._db_session_factory = db_session_factory

    def fetch_all(
        self,
        queries: list[tuple[str, SourceQuery]],
        timeout_per_source: int = 30,
    ) -> list[SourceResult]:
        """Fetch from multiple sources in parallel. Never raises; errors go into SourceResult.errors."""
        results: list[SourceResult] = []

        def _fetch_one(source_id: str, query: SourceQuery) -> SourceResult:
            t0 = time.monotonic()
            try:
                client = get_client(source_id, self._config, self._db_session_factory)
                result = client.fetch(query)
                latency_ms = int((time.monotonic() - t0) * 1000)
                logger.info(
                    "source=%s docs=%d errors=%d latency_ms=%d",
                    source_id, len(result.documents), len(result.errors), latency_ms,
                )
                return result
            except Exception as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                logger.warning("source=%s error=%s latency_ms=%d", source_id, exc, latency_ms)
                return SourceResult(
                    source=source_id,
                    query=query,
                    documents=[],
                    fetched_at=datetime.now(timezone.utc),
                    errors=[str(exc)],
                )

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_map = {
                executor.submit(_fetch_one, sid, q): (sid, q)
                for sid, q in queries
            }
            for future in as_completed(future_map, timeout=timeout_per_source * len(queries) + 60):
                sid, q = future_map[future]
                try:
                    results.append(future.result(timeout=timeout_per_source))
                except TimeoutError:
                    logger.warning("source=%s timed out", sid)
                    results.append(SourceResult(
                        source=sid, query=q, documents=[],
                        fetched_at=datetime.now(timezone.utc),
                        errors=["timeout"],
                    ))
                except Exception as exc:
                    results.append(SourceResult(
                        source=sid, query=q, documents=[],
                        fetched_at=datetime.now(timezone.utc),
                        errors=[str(exc)],
                    ))

        return results

    def fetch_for_ticker(
        self,
        ticker: str,
        sector_id: str,
        lookback_days_quant: int = 7,
        lookback_days_qual: int = 14,
    ) -> list[SourceResult]:
        """Build appropriate SourceQuery per available source and fetch in parallel."""
        available = list_available_sources(self._config)

        # sector_routed sources: skip if they don't match the active sector
        from src.sources.registry import SOURCE_REGISTRY, _register_all
        if not SOURCE_REGISTRY:
            _register_all()

        queries: list[tuple[str, SourceQuery]] = []
        for source_id in available:
            cls = SOURCE_REGISTRY.get(source_id)
            if cls is None:
                continue

            if cls.sector_routed:
                # Only include if this sector is in the config's specialist_sources
                sector_cfg = None
                for s in self._config.sectors:
                    if s.id == sector_id:
                        sector_cfg = s
                        break
                if sector_cfg is None or source_id not in sector_cfg.specialist_sources:
                    continue

            # Build query based on source type
            is_qualitative = source_id in {
                "guardian", "newsapi", "newsdata", "marketaux", "finnhub",
                "tavily", "firecrawl", "gdelt", "hackernews",
            }
            lookback = lookback_days_qual if is_qualitative else lookback_days_quant

            query = SourceQuery(
                ticker=ticker,
                query_string=ticker,
                lookback_days=lookback,
                limit=25,
                sector_id=sector_id,
            )
            queries.append((source_id, query))

        return self.fetch_all(queries)
