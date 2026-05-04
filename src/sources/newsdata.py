"""Newsdata.io client — free tier 200/day; is_fallback=True."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class NewsdataClient(BaseSourceClient):
    source_id = "newsdata"
    needs_key = True
    key_env_var = "NEWSDATA_API_KEY"
    rate_limit_per_sec = 0.5
    is_fallback = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()

        cached = self._cached(query)
        if cached:
            return cached

        q = query.query_string or query.ticker or "AI"
        key = os.environ.get("NEWSDATA_API_KEY", "")
        params = {
            "apikey": key,
            "q": q,
            "language": "en",
            "size": min(query.limit, 50),
        }

        try:
            resp = self._http_get("https://newsdata.io/api/1/news", params=params)
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

        documents: list[SourceDocument] = []
        for result in data.get("results", []):
            pub_raw = result.get("pubDate", "")
            published_at: Optional[datetime] = None
            if pub_raw:
                try:
                    published_at = datetime.strptime(pub_raw, "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass

            article_id = result.get("article_id", "")
            title = result.get("title", "")
            content_hash = self._content_hash(article_id + title)

            documents.append(
                SourceDocument(
                    source=self.source_id,
                    source_id=article_id,
                    url=result.get("link", ""),
                    content_hash=content_hash,
                    doc_type="news",
                    title=title,
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload=result,
                )
            )

        result_obj = SourceResult(
            source=self.source_id,
            query=query,
            documents=documents,
            fetched_at=self._utcnow(),
        )
        self._cache(query, result_obj)
        return result_obj
