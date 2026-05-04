"""OpenAlex — uses polite-pool mailto."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class OpenAlexClient(BaseSourceClient):
    source_id = "openalex"
    needs_key = False
    rate_limit_per_sec = 5.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            lookback = query.lookback_days or 14
            from_date = (date.today() - timedelta(days=lookback)).isoformat()

            if query.extra.get("concept_id"):
                params: dict[str, Any] = {
                    "filter": f"concepts.id:{query.extra['concept_id']},from_publication_date:{from_date}",
                    "per-page": min(query.limit, 50),
                    "mailto": "projectgemini53@gmail.com",
                }
            else:
                q = query.query_string or query.ticker or "artificial intelligence"
                params = {
                    "search": q,
                    "filter": f"from_publication_date:{from_date}",
                    "per-page": min(query.limit, 50),
                    "mailto": "projectgemini53@gmail.com",
                }

            resp = self._http_get("https://api.openalex.org/works", params=params)
            data = resp.json()

            works = data.get("results", [])
            docs = []
            for w in works:
                oa_id = w.get("id", "").split("/")[-1]
                title = w.get("title", "") or ""
                doi = w.get("doi", "") or ""
                url_w = doi if doi else w.get("id", "")
                pub_year = w.get("publication_year")
                pub_date_str = w.get("publication_date", "")

                published_at: Optional[datetime] = None
                try:
                    if pub_date_str:
                        published_at = datetime.strptime(pub_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    elif pub_year:
                        published_at = datetime(pub_year, 1, 1, tzinfo=timezone.utc)
                except Exception:
                    published_at = datetime(pub_year, 1, 1, tzinfo=timezone.utc) if pub_year else None

                citation_count = w.get("cited_by_count", 0)
                content_hash = self._content_hash(oa_id or title)

                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=oa_id,
                    url=url_w,
                    content_hash=content_hash,
                    doc_type="paper",
                    title=title,
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "openalex_id": oa_id,
                        "doi": doi,
                        "cited_by_count": citation_count,
                        "concepts": [
                            c.get("display_name", "")
                            for c in (w.get("concepts") or [])[:5]
                        ],
                    },
                    summary=f"cited {citation_count}x",
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
