"""EIA (U.S. Energy Information Administration) client — sector_routed=True (oil/gas/energy only)."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class EiaClient(BaseSourceClient):
    source_id = "eia"
    needs_key = True
    key_env_var = "EIA_API_KEY"
    rate_limit_per_sec = 2.0
    sector_routed = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()

        cached = self._cached(query)
        if cached:
            return cached

        dataset = query.extra.get("dataset", "petroleum")
        key = os.environ.get("EIA_API_KEY", "")

        if dataset == "electricity":
            url = (
                f"https://api.eia.gov/v2/electricity/rto/region-data/data"
                f"?frequency=daily&api_key={key}"
                f"&data[]=value&offset=0&length=30"
                f"&sort[0][column]=period&sort[0][direction]=desc"
            )
        else:
            # Default: petroleum
            url = (
                f"https://api.eia.gov/v2/petroleum/pri/spt/data"
                f"?frequency=daily&api_key={key}"
                f"&data[]=value&facets[series][]=RBRTE&offset=0&length=30"
                f"&sort[0][column]=period&sort[0][direction]=desc"
            )

        try:
            resp = self._http_get(url)
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

        items = data.get("response", {}).get("data", [])
        content_hash = self._content_hash(dataset + str(self._utcnow().date()))

        doc = SourceDocument(
            source=self.source_id,
            source_id=dataset,
            url=f"https://www.eia.gov/",
            content_hash=content_hash,
            doc_type="macro_indicator",
            title=f"EIA {dataset} data",
            published_at=self._utcnow(),
            fetched_at=self._utcnow(),
            raw_payload={"dataset": dataset, "data": items},
        )

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=[doc],
            fetched_at=self._utcnow(),
        )
        self._cache(query, result)
        return result
