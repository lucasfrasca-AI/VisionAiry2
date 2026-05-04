"""FRED (Federal Reserve Economic Data) client."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class FredClient(BaseSourceClient):
    source_id = "fred"
    needs_key = True
    key_env_var = "FRED_API_KEY"
    rate_limit_per_sec = 5.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()

        cached = self._cached(query)
        if cached:
            return cached

        series_id = query.query_string or "DGS10"
        lookback = query.lookback_days or 365
        d1 = (datetime.now(timezone.utc) - timedelta(days=lookback)).strftime("%Y-%m-%d")
        key = os.environ.get("FRED_API_KEY", "")
        params = {
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "observation_start": d1,
            "limit": min(query.limit, 1000),
        }

        try:
            resp = self._http_get(
                "https://api.stlouisfed.org/fred/series/observations", params=params
            )
            data = resp.json()
        except (SourceAuthError, SourceRateLimitError):
            raise
        except Exception as exc:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=self._utcnow(),
                errors=[str(exc)],
            )

        observations = data.get("observations", [])
        content_hash = self._content_hash(series_id + d1 + str(len(observations)))

        doc = SourceDocument(
            source=self.source_id,
            source_id=series_id,
            url=f"https://fred.stlouisfed.org/series/{series_id}",
            content_hash=content_hash,
            doc_type="macro_indicator",
            title=f"FRED {series_id} observations",
            published_at=self._utcnow(),
            fetched_at=self._utcnow(),
            raw_payload={"series_id": series_id, "observations": observations},
        )

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=[doc],
            fetched_at=self._utcnow(),
        )
        self._cache(query, result)
        return result
