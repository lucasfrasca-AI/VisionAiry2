from __future__ import annotations

import logging
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

log = logging.getLogger("visionairy2.sources.finnhub")

_FINANCIAL_DOMAINS = frozenset({
    "wsj.com", "bloomberg.com", "reuters.com", "ft.com", "cnbc.com",
    "marketwatch.com", "barrons.com", "seekingalpha.com", "fool.com",
    "benzinga.com", "finance.yahoo.com", "yahoo.com/finance",
    "businesswire.com", "prnewswire.com", "globenewswire.com",
    "sec.gov", "investors.com", "theinformation.com", "axios.com",
    "investing.com", "thestreet.com", "zacks.com",
})

_BUSINESS_KEYWORDS = frozenset({
    "earnings", "revenue", "profit", "loss", "guidance", "dividend",
    "buyback", "ceo", "cfo", "cto", "layoff", "hire", "fire", "lawsuit",
    "settlement", "regulator", "fda", "approval", "contract", "merger",
    "acquisition", "ipo", "spinoff", "debt", "bond", "downgrade", "upgrade",
    "rating", "target", "analyst", "beats", "misses", "estimate", "forecast",
    "quarterly", "fiscal", "sec filing", "10-k", "10-q", "8-k", "proxy",
    "insider", "stock", "share", "valuation", "market cap", "eps", "ebitda",
    "cash flow", "balance sheet",
})


class FinnhubClient(BaseSourceClient):
    source_id = "finnhub"
    needs_key = True
    key_env_var = "FINNHUB_API_KEY"
    rate_limit_per_sec = 1.0

    def _is_business_relevant(self, article: dict, ticker: str) -> bool:
        """Return True if article is plausibly about the company, not just a name mention."""
        headline = article.get("headline", "")
        headline_lower = headline.lower()
        url = article.get("url", "").lower()

        # 1. Headline contains ticker in $TICKER or (TICKER) form
        ticker_upper = ticker.upper()
        if f"${ticker_upper}" in headline or f"({ticker_upper})" in headline:
            return True

        # 2. URL is from a recognised financial-press domain
        for domain in _FINANCIAL_DOMAINS:
            if domain in url:
                return True

        # 3. Headline contains a business-context keyword
        for kw in _BUSINESS_KEYWORDS:
            if kw in headline_lower:
                return True

        return False

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
                all_items = resp.json() or []
                n_total = len(all_items[: query.limit])
                items = [i for i in all_items[: query.limit] if self._is_business_relevant(i, ticker)]
                n_kept = len(items)
                if n_total > 0:
                    log.info(
                        "finnhub: kept %d of %d articles for %s after relevance filter",
                        n_kept, n_total, ticker,
                    )
                if n_total > 0 and n_kept == 0:
                    result = SourceResult(
                        source=self.source_id,
                        query=query,
                        documents=[],
                        fetched_at=fetched_at,
                        errors=[
                            f"all {n_total} articles dropped by relevance filter; "
                            f"consider verifying ticker={ticker} name overlap"
                        ],
                    )
                    self._cache(query, result)
                    return result
                for item in items:
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
