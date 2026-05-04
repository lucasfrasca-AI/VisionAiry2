"""GitHub repository search client."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class GithubClient(BaseSourceClient):
    source_id = "github"
    needs_key = True
    key_env_var = "GITHUB_TOKEN"
    rate_limit_per_sec = 4.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()

        cached = self._cached(query)
        if cached:
            return cached

        if query.query_string:
            q = query.query_string
        elif query.ticker:
            q = f"{query.ticker} technology"
        else:
            q = "AI machine learning"

        key = os.environ.get("GITHUB_TOKEN", "")
        headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "VisionAiry2",
        }
        params: dict[str, Any] = {
            "q": f"{q}+stars:>100",
            "sort": "stars",
            "order": "desc",
            "per_page": min(query.limit, 30),
        }

        try:
            resp = self._http_get(
                "https://api.github.com/search/repositories",
                params=params,
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

        documents: list[SourceDocument] = []
        _keep_keys = [
            "id", "full_name", "description", "stargazers_count",
            "pushed_at", "language", "topics",
        ]

        for item in data.get("items", []):
            repo_id = str(item.get("id", ""))
            published_at = _parse_iso(item.get("pushed_at") or item.get("created_at"))
            content_hash = self._content_hash(repo_id)
            raw_payload = {k: item[k] for k in _keep_keys if k in item}

            documents.append(
                SourceDocument(
                    source=self.source_id,
                    source_id=repo_id,
                    url=item.get("html_url", ""),
                    content_hash=content_hash,
                    doc_type="tech_signal",
                    title=item.get("full_name", ""),
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload=raw_payload,
                    entities_mentioned=item.get("topics", []),
                )
            )

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=documents,
            fetched_at=self._utcnow(),
        )
        self._cache(query, result)
        return result
