"""Firecrawl scraper client.

KNOWN ISSUE: Session 1 validate-keys used a GET on /v1/scrape which returns 404.
The correct endpoint is POST /v1/scrape — confirmed working. This client uses POST.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class FirecrawlClient(BaseSourceClient):
    source_id = "firecrawl"
    needs_key = True
    key_env_var = "FIRECRAWL_API_KEY"
    rate_limit_per_sec = 1.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()

        cached = self._cached(query)
        if cached:
            return cached

        url_to_scrape = query.query_string or ""
        if not url_to_scrape:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=self._utcnow(),
                errors=["query_string must be a URL to scrape"],
            )

        key = os.environ.get("FIRECRAWL_API_KEY", "")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "url": url_to_scrape,
            "formats": ["markdown"],
        }

        try:
            resp = self._http_post(
                "https://api.firecrawl.dev/v1/scrape",
                json=body,
                headers=headers,
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

        content = data.get("data", {}).get("markdown", "")
        metadata = data.get("data", {}).get("metadata", {})
        title = metadata.get("title", "") or url_to_scrape
        content_hash = self._content_hash(url_to_scrape + content[:500])

        doc = SourceDocument(
            source=self.source_id,
            source_id=url_to_scrape,
            url=url_to_scrape,
            content_hash=content_hash,
            doc_type="scraped_page",
            title=title,
            published_at=None,
            fetched_at=self._utcnow(),
            raw_payload={
                "url": url_to_scrape,
                "markdown": content[:5000],
                "metadata": metadata,
            },
            summary=content[:500],
        )

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=[doc],
            fetched_at=self._utcnow(),
        )
        self._cache(query, result)
        return result
