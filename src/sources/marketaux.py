from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

from src.sources.base import (
    BaseSourceClient,
    SourceDocument,
    SourceQuery,
    SourceResult,
    SourceAuthError,
    SourceRateLimitError,
)


class MarketauxClient(BaseSourceClient):
    source_id = "marketaux"
    needs_key = True
    key_env_var = "MARKETAUX_API_KEY"
    rate_limit_per_sec = 0.5

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()
        cached = self._cached(query)
        if cached:
            return cached

        key = os.environ.get("MARKETAUX_API_KEY", "")
        ticker = query.ticker or ""
        lookback = query.lookback_days or 7
        d1 = (datetime.now(timezone.utc) - timedelta(days=lookback)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        fetched_at = self._utcnow()
        docs: list[SourceDocument] = []

        try:
            resp = self._http_get(
                "https://api.marketaux.com/v1/news/all",
                params={
                    "symbols": ticker,
                    "filter_entities": "true",
                    "language": "en",
                    "api_token": key,
                    "published_after": d1,
                    "limit": min(query.limit, 20),
                },
            )
            data = resp.json() or {}
            articles = data.get("data", [])
            for article in articles[: query.limit]:
                uuid = article.get("uuid", "")
                title = article.get("title", "")
                pub_str = article.get("published_at", "")
                published_at = None
                if pub_str:
                    try:
                        published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                entities = [
                    e.get("symbol", "")
                    for e in article.get("entities", [])
                    if e.get("symbol")
                ]
                content_hash = self._content_hash(uuid + title)
                docs.append(
                    SourceDocument(
                        source=self.source_id,
                        source_id=uuid,
                        url=article.get("url", ""),
                        content_hash=content_hash,
                        doc_type="news",
                        title=title,
                        published_at=published_at,
                        fetched_at=fetched_at,
                        raw_payload=article,
                        entities_mentioned=entities,
                    )
                )

            result = SourceResult(
                source=self.source_id,
                query=query,
                documents=docs,
                fetched_at=fetched_at,
            )

        except (SourceAuthError, SourceRateLimitError):
            raise
        except Exception as exc:
            result = SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=fetched_at,
                errors=[str(exc)],
            )

        self._cache(query, result)
        return result
