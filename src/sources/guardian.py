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


class GuardianClient(BaseSourceClient):
    source_id = "guardian"
    needs_key = True
    key_env_var = "GUARDIAN_API_KEY"
    rate_limit_per_sec = 2.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()
        cached = self._cached(query)
        if cached:
            return cached

        key = os.environ.get("GUARDIAN_API_KEY", "")
        q = query.query_string or query.ticker or "AI technology"
        lookback = query.lookback_days or 7
        d1 = (datetime.now(timezone.utc) - timedelta(days=lookback)).strftime("%Y-%m-%d")
        fetched_at = self._utcnow()
        docs: list[SourceDocument] = []

        try:
            resp = self._http_get(
                "https://content.guardianapis.com/search",
                params={
                    "section": "business",
                    "order-by": "newest",
                    "show-fields": "trailText,bodyText",
                    "q": q,
                    "api-key": key,
                    "from-date": d1,
                    "page-size": min(query.limit, 50),
                },
            )
            data = resp.json() or {}
            results = data.get("response", {}).get("results", [])
            for result_item in results[: query.limit]:
                gid = result_item.get("id", "")
                title = result_item.get("webTitle", "")
                pub_str = result_item.get("webPublicationDate", "")
                published_at = None
                if pub_str:
                    try:
                        published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                content_hash = self._content_hash(gid + title)
                docs.append(
                    SourceDocument(
                        source=self.source_id,
                        source_id=gid,
                        url=result_item.get("webUrl", ""),
                        content_hash=content_hash,
                        doc_type="news",
                        title=title,
                        published_at=published_at,
                        fetched_at=fetched_at,
                        raw_payload=result_item,
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
