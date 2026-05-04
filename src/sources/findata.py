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


class FinancialDatasetsClient(BaseSourceClient):
    source_id = "findata"
    needs_key = True
    key_env_var = "FINANCIAL_DATASETS_API_KEY"
    rate_limit_per_sec = 1.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()
        cached = self._cached(query)
        if cached:
            return cached

        key = os.environ.get("FINANCIAL_DATASETS_API_KEY", "")
        ticker = query.ticker or ""
        endpoint = query.extra.get("endpoint", "income")
        fetched_at = self._utcnow()
        headers = {"X-API-KEY": key}
        docs: list[SourceDocument] = []

        try:
            if endpoint == "income":
                resp = self._http_get(
                    "https://api.financialdatasets.ai/financials/income-statements",
                    params={"ticker": ticker, "limit": query.limit},
                    headers=headers,
                )
                data = resp.json() or {}
                items = data.get("income_statements", [])
                for item in items[: query.limit]:
                    period = item.get("period_of_report", "")
                    title = f"income {ticker} {period}"
                    uid = self._content_hash(title + str(item))
                    docs.append(
                        SourceDocument(
                            source=self.source_id,
                            source_id=uid[:16],
                            url=f"https://api.financialdatasets.ai/financials/income-statements?ticker={ticker}",
                            content_hash=self._content_hash(uid),
                            doc_type="market_data",
                            title=title,
                            published_at=None,
                            fetched_at=fetched_at,
                            raw_payload=item,
                        )
                    )

            elif endpoint == "balance":
                resp = self._http_get(
                    "https://api.financialdatasets.ai/financials/balance-sheets",
                    params={"ticker": ticker, "limit": query.limit},
                    headers=headers,
                )
                data = resp.json() or {}
                items = data.get("balance_sheets", [])
                for item in items[: query.limit]:
                    period = item.get("period_of_report", "")
                    title = f"balance {ticker} {period}"
                    uid = self._content_hash(title + str(item))
                    docs.append(
                        SourceDocument(
                            source=self.source_id,
                            source_id=uid[:16],
                            url=f"https://api.financialdatasets.ai/financials/balance-sheets?ticker={ticker}",
                            content_hash=self._content_hash(uid),
                            doc_type="market_data",
                            title=title,
                            published_at=None,
                            fetched_at=fetched_at,
                            raw_payload=item,
                        )
                    )

            elif endpoint == "price":
                resp = self._http_get(
                    "https://api.financialdatasets.ai/prices/snapshot",
                    params={"ticker": ticker},
                    headers=headers,
                )
                data = resp.json() or {}
                uid = self._content_hash(ticker + "price_snapshot")
                docs.append(
                    SourceDocument(
                        source=self.source_id,
                        source_id=uid[:16],
                        url=f"https://api.financialdatasets.ai/prices/snapshot?ticker={ticker}",
                        content_hash=self._content_hash(uid),
                        doc_type="market_data",
                        title=f"price {ticker}",
                        published_at=None,
                        fetched_at=fetched_at,
                        raw_payload=data,
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
