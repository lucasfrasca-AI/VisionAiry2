"""Wikidata entity search — used for company name -> QID resolution."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class WikidataClient(BaseSourceClient):
    source_id = "wikidata"
    needs_key = False
    rate_limit_per_sec = 5.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        q = query.query_string or query.ticker or ""
        if not q:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=self._utcnow(),
                errors=["query_string or ticker required"],
            )

        try:
            params: dict[str, Any] = {
                "action": "wbsearchentities",
                "search": q,
                "language": "en",
                "format": "json",
                "type": "item",
                "limit": min(query.limit, 20),
            }

            resp = self._http_get(
                "https://www.wikidata.org/w/api.php",
                params=params,
                headers={"User-Agent": "VisionAiry2/1.0 (projectgemini53@gmail.com)"},
            )
            data = resp.json()

            items = data.get("search", [])
            docs = []
            for item in items:
                qid = item.get("id", "")
                label = item.get("label", "")
                description = item.get("description", "")
                url_w = item.get("url", "") or f"https://www.wikidata.org/wiki/{qid}"
                content_hash = self._content_hash(qid)

                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=qid,
                    url=url_w,
                    content_hash=content_hash,
                    doc_type="other",
                    title=label,
                    published_at=None,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "qid": qid,
                        "label": label,
                        "description": description,
                        "aliases": item.get("aliases", []),
                    },
                    summary=description,
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
