"""GDELT Project — public news sentiment/event feed."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class GdeltClient(BaseSourceClient):
    source_id = "gdelt"
    needs_key = False
    rate_limit_per_sec = 2.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            q = query.query_string or query.ticker or "AI technology"
            lookback = query.lookback_days or 7
            span = f"{min(lookback, 7)}d"
            params: dict[str, Any] = {
                "query": q,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": min(query.limit, 75),
                "timespan": span,
            }

            resp = self._http_get("https://api.gdeltproject.org/api/v2/doc/doc", params=params)

            try:
                data = resp.json()
            except Exception:
                return SourceResult(
                    source=self.source_id,
                    query=query,
                    documents=[],
                    fetched_at=self._utcnow(),
                    errors=["GDELT returned non-JSON"],
                )

            articles = data.get("articles", []) if data else []
            docs = []
            for art in articles:
                url_a = art.get("url", "")
                title = art.get("title", "")
                date_str = art.get("seendate", "")

                published_at: Optional[datetime] = None
                try:
                    if date_str:
                        published_at = datetime.strptime(date_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                except Exception:
                    published_at = None

                content_hash = self._content_hash(url_a + title)
                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=url_a,
                    url=url_a,
                    content_hash=content_hash,
                    doc_type="news",
                    title=title,
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "url": url_a,
                        "domain": art.get("domain", ""),
                        "language": art.get("language", ""),
                        "sourcecountry": art.get("sourcecountry", ""),
                    },
                ))

            result = SourceResult(
                source=self.source_id,
                query=query,
                documents=docs,
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
