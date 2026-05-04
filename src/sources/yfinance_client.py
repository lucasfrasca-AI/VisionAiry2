"""yfinance client — scraper-based, no key needed; is_fallback=True."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class YfinanceClient(BaseSourceClient):
    source_id = "yfinance"
    needs_key = False
    key_env_var = None
    rate_limit_per_sec = 0.5
    is_fallback = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        # No self._guard_available() — needs_key=False

        ticker = query.ticker
        if not ticker:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=self._utcnow(),
                errors=["ticker required"],
            )

        cached = self._cached(query)
        if cached:
            return cached

        mode = query.extra.get("mode", "info")
        documents: list[SourceDocument] = []
        errors: list[str] = []

        import yfinance as yf  # noqa: PLC0415

        try:
            t = yf.Ticker(ticker)

            if mode in ("info", "all"):
                try:
                    info = t.info or {}
                    if info:
                        h = self._content_hash(
                            ticker + "info" + str(info.get("regularMarketPrice", ""))
                        )
                        documents.append(
                            SourceDocument(
                                source=self.source_id,
                                source_id=f"{ticker}_info",
                                url=f"https://finance.yahoo.com/quote/{ticker}",
                                content_hash=h,
                                doc_type="market_data",
                                title=f"yfinance info {ticker}",
                                published_at=self._utcnow(),
                                fetched_at=self._utcnow(),
                                raw_payload={
                                    "ticker": ticker,
                                    "info": {
                                        k: v
                                        for k, v in info.items()
                                        if not isinstance(v, (dict, list))
                                    },
                                },
                            )
                        )
                except Exception as exc:
                    errors.append(f"info: {exc}")

            if mode in ("history", "all"):
                try:
                    period = query.extra.get("period", "2y")
                    hist = t.history(period=period)
                    if not hist.empty:
                        records = hist.tail(10).reset_index().to_dict("records")
                        h = self._content_hash(ticker + "history" + str(hist.index[-1]))
                        documents.append(
                            SourceDocument(
                                source=self.source_id,
                                source_id=f"{ticker}_history",
                                url=f"https://finance.yahoo.com/quote/{ticker}/history",
                                content_hash=h,
                                doc_type="market_data",
                                title=f"yfinance history {ticker}",
                                published_at=self._utcnow(),
                                fetched_at=self._utcnow(),
                                raw_payload={
                                    "ticker": ticker,
                                    "recent_bars": [
                                        {str(k): str(v) for k, v in r.items()}
                                        for r in records
                                    ],
                                },
                            )
                        )
                except Exception as exc:
                    errors.append(f"history: {exc}")

            if mode in ("holders", "all"):
                try:
                    holders = t.major_holders
                    if holders is not None and not holders.empty:
                        h = self._content_hash(ticker + "holders")
                        documents.append(
                            SourceDocument(
                                source=self.source_id,
                                source_id=f"{ticker}_holders",
                                url=f"https://finance.yahoo.com/quote/{ticker}/holders",
                                content_hash=h,
                                doc_type="market_data",
                                title=f"yfinance holders {ticker}",
                                published_at=self._utcnow(),
                                fetched_at=self._utcnow(),
                                raw_payload={
                                    "ticker": ticker,
                                    "major_holders": holders.to_dict(),
                                },
                            )
                        )
                except Exception as exc:
                    errors.append(f"holders: {exc}")

        except Exception as exc:
            errors.append(str(exc))

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=documents,
            fetched_at=self._utcnow(),
            errors=errors,
        )
        self._cache(query, result)
        return result
