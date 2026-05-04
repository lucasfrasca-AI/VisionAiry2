"""bioRxiv/medRxiv client — sector_routed=True (pharma/biotech)."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class BiorxivClient(BaseSourceClient):
    source_id = "biorxiv"
    needs_key = False
    rate_limit_per_sec = 1.0
    sector_routed = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            server = query.extra.get("server", "biorxiv")
            lookback = query.lookback_days or 14
            today = date.today()
            from_date = (today - timedelta(days=lookback)).isoformat()
            to_date = today.isoformat()
            cursor = query.extra.get("cursor", 0)

            url = f"https://api.biorxiv.org/details/{server}/{from_date}/{to_date}/{cursor}"
            resp = self._http_get(url)
            data = resp.json()

            papers = data.get("collection", [])[:min(query.limit, 100)]
            docs = []
            for paper in papers:
                doi = paper.get("doi", "")
                title = paper.get("title", "")
                abstract = paper.get("abstract", "")[:300]
                published_str = paper.get("date", "")

                published_at: Optional[datetime] = None
                try:
                    if published_str:
                        published_at = datetime.strptime(published_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except Exception:
                    published_at = None

                url_paper = f"https://www.biorxiv.org/content/{doi}v1" if doi else ""
                content_hash = self._content_hash(doi or title)

                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=doi,
                    url=url_paper,
                    content_hash=content_hash,
                    doc_type="paper",
                    title=title,
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "doi": doi,
                        "authors": paper.get("authors", ""),
                        "category": paper.get("category", ""),
                        "abstract": abstract,
                    },
                    summary=abstract,
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
