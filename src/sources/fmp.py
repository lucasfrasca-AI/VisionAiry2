from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from src.sources.base import (
    BaseSourceClient,
    SourceDocument,
    SourceQuery,
    SourceResult,
    SourceAuthError,
    SourceRateLimitError,
)

# FMP key is INVALID as of Session 1; is_available() gates it off at runtime.


class FMPClient(BaseSourceClient):
    source_id = "fmp"
    needs_key = True
    key_env_var = "FMP_API_KEY"
    rate_limit_per_sec = 0.5

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()
        cached = self._cached(query)
        if cached:
            return cached

        key = os.environ.get("FMP_API_KEY", "")
        ticker = query.ticker or ""
        endpoint = query.extra.get("endpoint", "profile")
        fetched_at = self._utcnow()
        docs: list[SourceDocument] = []

        _endpoint_map: dict[str, tuple[str, str]] = {
            "profile": (
                f"https://financialmodelingprep.com/api/v3/profile/{ticker}",
                "market_data",
            ),
            "income": (
                f"https://financialmodelingprep.com/api/v3/income-statement/{ticker}",
                "filing",
            ),
            "key-metrics": (
                f"https://financialmodelingprep.com/api/v3/key-metrics/{ticker}",
                "market_data",
            ),
            "insider": (
                f"https://financialmodelingprep.com/api/v3/insider-trading",
                "insider",
            ),
        }

        try:
            url, doc_type = _endpoint_map.get(
                endpoint,
                (f"https://financialmodelingprep.com/api/v3/profile/{ticker}", "market_data"),
            )
            params: dict[str, Any] = {"apikey": key}
            if endpoint == "income":
                params.update({"period": "quarter", "limit": 8})
            elif endpoint == "key-metrics":
                params.update({"period": "quarter", "limit": 8})
            elif endpoint == "insider":
                params["symbol"] = ticker

            resp = self._http_get(url, params=params)
            items = resp.json() or []
            if isinstance(items, dict):
                items = [items]

            for item in items[: query.limit]:
                date_val = item.get("date", "")
                title = f"{endpoint} {ticker} {date_val}"
                uid = self._content_hash(title + str(item))
                docs.append(
                    SourceDocument(
                        source=self.source_id,
                        source_id=uid[:16],
                        url=url,
                        content_hash=self._content_hash(uid),
                        doc_type=doc_type,
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
