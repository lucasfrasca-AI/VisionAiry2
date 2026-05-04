from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any

from src.sources.base import (
    BaseSourceClient,
    SourceDocument,
    SourceQuery,
    SourceResult,
    SourceAuthError,
    SourceRateLimitError,
)


class FinnhubClient(BaseSourceClient):
    source_id = "finnhub"
    needs_key = True
    key_env_var = "FINNHUB_API_KEY"
    rate_limit_per_sec = 1.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()
        cached = self._cached(query)
        if cached:
            return cached

        key = os.environ.get("FINNHUB_API_KEY", "")
        ticker = query.ticker or ""
        endpoint = query.extra.get("endpoint", "company-news")
        now = datetime.now(timezone.utc)
        lookback = query.lookback_days or 14
        d1 = (now - timedelta(days=lookback)).strftime("%Y-%m-%d")
        d2 = now.strftime("%Y-%m-%d")
        fetched_at = self._utcnow()
        docs: list[SourceDocument] = []

        try:
            if endpoint == "company-news":
                resp = self._http_get(
                    "https://finnhub.io/api/v1/company-news",
                    params={"symbol": ticker, "from": d1, "to": d2, "token": key},
                )
                items = resp.json() or []
                for item in items[: query.limit]:
                    raw_id = str(item.get("id", ""))
                    ts = item.get("datetime")
                    published_at = (
                        datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
                    )
                    uid = raw_id or self._content_hash(
                        item.get("headline", "") + item.get("url", "")
                    )
                    docs.append(
                        SourceDocument(
                            source=self.source_id,
                            source_id=uid,
                            url=item.get("url", ""),
                            content_hash=self._content_hash(uid),
                            doc_type="news",
                            title=item.get("headline", ""),
                            published_at=published_at,
                            fetched_at=fetched_at,
                            raw_payload=item,
                            summary=item.get("summary"),
                        )
                    )

            elif endpoint == "sentiment":
                resp = self._http_get(
                    "https://finnhub.io/api/v1/news-sentiment",
                    params={"symbol": ticker, "token": key},
                )
                data = resp.json() or {}
                uid = self._content_hash(ticker + "sentiment")
                docs.append(
                    SourceDocument(
                        source=self.source_id,
                        source_id=uid[:16],
                        url=f"https://finnhub.io/api/v1/news-sentiment?symbol={ticker}",
                        content_hash=self._content_hash(uid),
                        doc_type="sentiment",
                        title=f"Sentiment {ticker}",
                        published_at=None,
                        fetched_at=fetched_at,
                        raw_payload=data,
                    )
                )

            elif endpoint == "insider":
                resp = self._http_get(
                    "https://finnhub.io/api/v1/stock/insider-transactions",
                    params={"symbol": ticker, "from": d1, "to": d2, "token": key},
                )
                data = resp.json() or {}
                items = data.get("data", [])
                for item in items[: query.limit]:
                    uid = self._content_hash(
                        str(item.get("name", ""))
                        + str(item.get("transactionDate", ""))
                        + str(item.get("share", ""))
                    )
                    docs.append(
                        SourceDocument(
                            source=self.source_id,
                            source_id=uid[:16],
                            url="",
                            content_hash=self._content_hash(uid),
                            doc_type="insider",
                            title=f"Insider {ticker} {item.get('name','')} {item.get('transactionDate','')}",
                            published_at=None,
                            fetched_at=fetched_at,
                            raw_payload=item,
                        )
                    )

            elif endpoint == "earnings":
                resp = self._http_get(
                    "https://finnhub.io/api/v1/calendar/earnings",
                    params={"from": d1, "to": d2, "symbol": ticker, "token": key},
                )
                data = resp.json() or {}
                items = data.get("earningsCalendar", [])
                for item in items[: query.limit]:
                    uid = self._content_hash(
                        ticker + str(item.get("date", "")) + str(item.get("epsActual", ""))
                    )
                    docs.append(
                        SourceDocument(
                            source=self.source_id,
                            source_id=uid[:16],
                            url="",
                            content_hash=self._content_hash(uid),
                            doc_type="earnings",
                            title=f"Earnings {ticker} {item.get('date','')}",
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
