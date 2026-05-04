"""Crossref — uses polite-pool mailto."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class CrossrefClient(BaseSourceClient):
    source_id = "crossref"
    needs_key = False
    rate_limit_per_sec = 5.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            q = query.query_string or query.ticker or "AI"
            lookback = query.lookback_days or 30
            from_date = (date.today() - timedelta(days=lookback)).strftime("%Y-%m-%d")
            params: dict[str, Any] = {
                "query": q,
                "filter": f"from-pub-date:{from_date}",
                "rows": min(query.limit, 50),
                "mailto": "projectgemini53@gmail.com",
            }

            resp = self._http_get("https://api.crossref.org/works", params=params)
            data = resp.json()

            items = data.get("message", {}).get("items", [])
            docs = []
            for item in items:
                doi = item.get("DOI", "")
                title_list = item.get("title", [])
                title = title_list[0] if title_list else doi
                url_item = f"https://doi.org/{doi}" if doi else ""

                pub_parts = item.get("published", {}).get("date-parts", [[]])
                pub_list = pub_parts[0] if pub_parts else []
                published_at: Optional[datetime] = None
                try:
                    if len(pub_list) >= 3:
                        published_at = datetime(pub_list[0], pub_list[1], pub_list[2], tzinfo=timezone.utc)
                    elif len(pub_list) >= 1:
                        published_at = datetime(pub_list[0], 1, 1, tzinfo=timezone.utc)
                except Exception:
                    published_at = None

                content_hash = self._content_hash(doi or title)
                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=doi,
                    url=url_item,
                    content_hash=content_hash,
                    doc_type="paper",
                    title=title,
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "doi": doi,
                        "type": item.get("type", ""),
                        "publisher": item.get("publisher", ""),
                        "is-referenced-by-count": item.get("is-referenced-by-count", 0),
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
