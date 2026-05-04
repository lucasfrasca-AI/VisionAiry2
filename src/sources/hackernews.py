"""Hacker News via Algolia search API."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class HackerNewsClient(BaseSourceClient):
    source_id = "hackernews"
    needs_key = False
    rate_limit_per_sec = 5.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            q = query.query_string or query.ticker or "AI"
            params: dict[str, Any] = {
                "query": q,
                "tags": "story",
                "numericFilters": "points>20",
                "hitsPerPage": min(query.limit, 50),
            }

            resp = self._http_get("http://hn.algolia.com/api/v1/search_by_date", params=params)
            data = resp.json()

            hits = data.get("hits", [])
            docs = []
            for hit in hits:
                object_id = hit.get("objectID", "")
                title = hit.get("title", "")
                url_h = hit.get("url", "") or f"https://news.ycombinator.com/item?id={object_id}"
                created_str = hit.get("created_at", "")

                published_at: Optional[datetime] = None
                try:
                    if created_str:
                        published_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except Exception:
                    published_at = None

                content_hash = self._content_hash(object_id)
                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=object_id,
                    url=url_h,
                    content_hash=content_hash,
                    doc_type="tech_signal",
                    title=title,
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "objectID": object_id,
                        "points": hit.get("points", 0),
                        "num_comments": hit.get("num_comments", 0),
                        "author": hit.get("author", ""),
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
