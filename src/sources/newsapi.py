from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

from src.sources.base import (
    BaseSourceClient,
    SourceDocument,
    SourceQuery,
    SourceResult,
    SourceAuthError,
    SourceRateLimitError,
)

# Dev tier: 100 requests/day; is_fallback=True to reflect limited quota.


class NewsAPIClient(BaseSourceClient):
    source_id = "newsapi"
    needs_key = True
    key_env_var = "NEWSAPI_KEY"
    rate_limit_per_sec = 0.5
    is_fallback = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()
        cached = self._cached(query)
        if cached:
            return cached

        key = os.environ.get("NEWSAPI_KEY", "")
        q = query.query_string or query.ticker or "AI"
        lookback = query.lookback_days or 7
        d1 = (datetime.now(timezone.utc) - timedelta(days=lookback)).strftime("%Y-%m-%d")
        fetched_at = self._utcnow()
        docs: list[SourceDocument] = []

        try:
            resp = self._http_get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": q,
                    "from": d1,
                    "sortBy": "relevancy",
                    "language": "en",
                    "apiKey": key,
                    "pageSize": min(query.limit, 100),
                },
            )

            # 426 or upgradeRequired indicates free-tier restriction
            if resp.status_code == 426:
                result = SourceResult(
                    source=self.source_id,
                    query=query,
                    documents=[],
                    fetched_at=fetched_at,
                    errors=["upgradeRequired: plan does not support this request"],
                )
                self._cache(query, result)
                return result

            data = resp.json() or {}
            if "upgradeRequired" in str(data.get("code", "")):
                result = SourceResult(
                    source=self.source_id,
                    query=query,
                    documents=[],
                    fetched_at=fetched_at,
                    errors=["upgradeRequired: " + data.get("message", "")],
                )
                self._cache(query, result)
                return result

            articles = data.get("articles", [])
            for article in articles[: query.limit]:
                url = article.get("url", "")
                title = article.get("title", "")
                pub_str = article.get("publishedAt", "")
                published_at = None
                if pub_str:
                    try:
                        published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                content_hash = self._content_hash(url + title)
                docs.append(
                    SourceDocument(
                        source=self.source_id,
                        source_id=url,
                        url=url,
                        content_hash=content_hash,
                        doc_type="news",
                        title=title,
                        published_at=published_at,
                        fetched_at=fetched_at,
                        raw_payload=article,
                    )
                )

            result = SourceResult(
                source=self.source_id,
                query=query,
                documents=docs,
                fetched_at=fetched_at,
            )

        except (SourceAuthError, SourceRateLimitError):
            raise
        except Exception as exc:
            result = SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=fetched_at,
                errors=[str(exc)],
            )

        self._cache(query, result)
        return result
