"""GitHub repository search client."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)

_ORG_INDICATOR = "organizations_url"


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
    emerging_signal = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        if query.extra.get("endpoint") == "topic-search":
            return self._fetch_topic_search(query)
        return self._fetch_keyword_search(query)

    def _fetch_keyword_search(self, query: SourceQuery) -> SourceResult:
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

    def _fetch_topic_search(self, query: SourceQuery) -> SourceResult:
        self._guard_available()
        cached = self._cached(query)
        if cached:
            return cached

        key = os.environ.get("GITHUB_TOKEN", "")
        headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "VisionAiry2",
        }
        lookback = query.lookback_days or 60
        since = (datetime.now(timezone.utc) - timedelta(days=lookback)).strftime("%Y-%m-%d")

        # Topics from query.extra or fall back to query_string as topic
        topics: list[str] = query.extra.get("topics") or []
        if not topics and query.query_string:
            topics = [query.query_string]

        documents: list[SourceDocument] = []
        errors: list[str] = []
        fetched_at = self._utcnow()

        for topic in topics[:5]:
            q_str = f"topic:{topic}+pushed:>{since}+stars:>100"
            params: dict[str, Any] = {
                "q": q_str,
                "sort": "stars",
                "order": "desc",
                "per_page": min(query.limit, 20),
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
                errors.append(f"topic {topic}: {exc}")
                continue

            _keep_keys = ["id", "full_name", "description", "stargazers_count", "pushed_at", "language", "topics", "owner"]
            for item in data.get("items", []):
                owner = item.get("owner") or {}
                # Only keep organisation-owned repos
                if owner.get("type", "").lower() != "organization":
                    continue
                org_name = owner.get("login") or ""
                repo_id = str(item.get("id", ""))
                published_at = _parse_iso(item.get("pushed_at") or item.get("created_at"))
                stars = item.get("stargazers_count", 0)
                raw_payload = {k: item[k] for k in _keep_keys if k in item}

                documents.append(SourceDocument(
                    source=self.source_id,
                    source_id=repo_id,
                    url=item.get("html_url", ""),
                    content_hash=self._content_hash(repo_id),
                    doc_type="tech_signal",
                    title=f"GitHub org: {org_name} (repo: {item.get('full_name', '')}, {stars} stars)",
                    published_at=published_at,
                    fetched_at=fetched_at,
                    raw_payload=raw_payload,
                    entities_mentioned=[org_name] if org_name else [],
                ))

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=documents,
            fetched_at=fetched_at,
            errors=errors,
        )
        self._cache(query, result)
        return result
