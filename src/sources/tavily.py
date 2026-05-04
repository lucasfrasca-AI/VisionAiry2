"""Tavily web search client."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class TavilyClient(BaseSourceClient):
    source_id = "tavily"
    needs_key = True
    key_env_var = "TAVILY_API_KEY"
    rate_limit_per_sec = 2.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()

        cached = self._cached(query)
        if cached:
            return cached

        q = query.query_string or query.ticker or "AI technology"
        key = os.environ.get("TAVILY_API_KEY", "")
        body: dict[str, Any] = {
            "api_key": key,
            "query": q,
            "search_depth": "basic",
            "max_results": min(query.limit, 10),
            "include_answer": False,
            "include_raw_content": True,
        }

        try:
            resp = self._http_post("https://api.tavily.com/search", json=body)
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
            url = result.get("url", "")
            title = result.get("title", "")
            content = result.get("raw_content") or result.get("content", "")
            content_hash = self._content_hash(url + title)

            documents.append(
                SourceDocument(
                    source=self.source_id,
                    source_id=url,
                    url=url,
                    content_hash=content_hash,
                    doc_type="web_search",
                    title=title,
                    published_at=None,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "url": url,
                        "title": title,
                        "content": content[:2000],
                        "score": result.get("score"),
                    },
                    summary=result.get("content", "")[:500],
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
