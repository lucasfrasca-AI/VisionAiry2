from __future__ import annotations

import os
from datetime import datetime, timezone

from src.sources.base import (
    BaseSourceClient,
    SourceDocument,
    SourceQuery,
    SourceResult,
    SourceAuthError,
    SourceRateLimitError,
)

# Free tier: 25 requests/day; is_fallback=True to reflect limited quota.


class AlphaVantageClient(BaseSourceClient):
    source_id = "alpha_vantage"
    needs_key = True
    key_env_var = "ALPHA_VANTAGE_API_KEY"
    rate_limit_per_sec = 0.05
    is_fallback = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()
        cached = self._cached(query)
        if cached:
            return cached

        key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        ticker = query.ticker or ""
        function = query.extra.get("function", "OVERVIEW")
        fetched_at = self._utcnow()
        docs: list[SourceDocument] = []

        try:
            if function == "OVERVIEW":
                resp = self._http_get(
                    "https://www.alphavantage.co/query",
                    params={"function": "OVERVIEW", "symbol": ticker, "apikey": key},
                )
                data = resp.json() or {}
                if "Note" in data or "Information" in data:
                    result = SourceResult(
                        source=self.source_id,
                        query=query,
                        documents=[],
                        fetched_at=fetched_at,
                        errors=["rate limited"],
                    )
                    self._cache(query, result)
                    return result
                uid = self._content_hash(ticker + "overview")
                docs.append(
                    SourceDocument(
                        source=self.source_id,
                        source_id=uid[:16],
                        url=f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}",
                        content_hash=self._content_hash(uid),
                        doc_type="market_data",
                        title=f"AV Overview {ticker}",
                        published_at=None,
                        fetched_at=fetched_at,
                        raw_payload=data,
                    )
                )

            elif function == "NEWS_SENTIMENT":
                resp = self._http_get(
                    "https://www.alphavantage.co/query",
                    params={"function": "NEWS_SENTIMENT", "tickers": ticker, "apikey": key},
                )
                data = resp.json() or {}
                if "Note" in data or "Information" in data:
                    result = SourceResult(
                        source=self.source_id,
                        query=query,
                        documents=[],
                        fetched_at=fetched_at,
                        errors=["rate limited"],
                    )
                    self._cache(query, result)
                    return result
                feed = data.get("feed", [])
                for item in feed[: query.limit]:
                    title = item.get("title", "")
                    uid = self._content_hash(item.get("url", "") + title)
                    docs.append(
                        SourceDocument(
                            source=self.source_id,
                            source_id=uid[:16],
                            url=item.get("url", ""),
                            content_hash=self._content_hash(uid),
                            doc_type="news",
                            title=title,
                            published_at=None,
                            fetched_at=fetched_at,
                            raw_payload=item,
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
