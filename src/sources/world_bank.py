"""World Bank macro indicators."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)

INDICATORS = {
    "NY.GDP.MKTP.KD.ZG": "GDP growth",
    "FP.CPI.TOTL.ZG": "Inflation CPI",
}


class WorldBankClient(BaseSourceClient):
    source_id = "world_bank"
    needs_key = False
    rate_limit_per_sec = 2.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            indicator = query.query_string or query.extra.get("indicator", "NY.GDP.MKTP.KD.ZG")
            year = query.extra.get("year", str(datetime.now(timezone.utc).year - 1))
            params: dict[str, Any] = {"format": "json", "date": year, "per_page": 100}
            url = f"https://api.worldbank.org/v2/country/all/indicator/{indicator}"

            resp = self._http_get(url, params=params)
            data = resp.json()

            if not isinstance(data, list) or len(data) < 2:
                return SourceResult(
                    source=self.source_id,
                    query=query,
                    documents=[],
                    fetched_at=self._utcnow(),
                    errors=["Unexpected World Bank response format"],
                )

            results = data[1] or []
            label = INDICATORS.get(indicator, indicator)

            content_hash = self._content_hash(indicator + year)
            doc = SourceDocument(
                source=self.source_id,
                source_id=f"{indicator}_{year}",
                url=f"https://data.worldbank.org/indicator/{indicator}",
                content_hash=content_hash,
                doc_type="macro_indicator",
                title=f"World Bank {label} {year}",
                published_at=datetime(int(year), 1, 1, tzinfo=timezone.utc) if year.isdigit() else None,
                fetched_at=self._utcnow(),
                raw_payload={
                    "indicator": indicator,
                    "year": year,
                    "data": [
                        {r.get("country", {}).get("value", ""): r.get("value")}
                        for r in results
                        if r.get("value") is not None
                    ],
                },
            )

            result = SourceResult(
                source=self.source_id,
                query=query,
                documents=[doc],
                fetched_at=self._utcnow(),
            )
            self._cache(query, result)
            return result

        except Exception as exc:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=self._utcnow(),
                errors=[str(exc)],
            )
