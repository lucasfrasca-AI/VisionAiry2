"""Papers With Code API."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class PapersWithCodeClient(BaseSourceClient):
    source_id = "papers_with_code"
    needs_key = False
    rate_limit_per_sec = 2.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            q = query.query_string or query.ticker or "deep learning"
            params: dict[str, Any] = {
                "q": q,
                "ordering": "-published",
                "items_per_page": min(query.limit, 50),
            }

            resp = self._http_get("https://paperswithcode.com/api/v1/papers/", params=params)
            data = resp.json()

            results = data.get("results", [])
            docs = []
            for paper in results:
                paper_id = str(paper.get("id", ""))
                title = paper.get("title", "")
                url_p = paper.get("url_pdf", "") or paper.get("url_abs", "") or ""
                pub_str = paper.get("published", "")

                published_at: Optional[datetime] = None
                try:
                    if pub_str:
                        published_at = datetime.strptime(pub_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except Exception:
                    published_at = None

                content_hash = self._content_hash(paper_id or title)
                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=paper_id,
                    url=url_p,
                    content_hash=content_hash,
                    doc_type="paper",
                    title=title,
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "id": paper_id,
                        "arxiv_id": paper.get("arxiv_id", ""),
                        "stars": paper.get("stars", 0),
                        "tasks": paper.get("tasks", [])[:3],
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
