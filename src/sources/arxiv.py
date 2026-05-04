"""arXiv preprint search client."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional
import xml.etree.ElementTree as ET

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)

ATOM_NS = "http://www.w3.org/2005/Atom"


class ArxivClient(BaseSourceClient):
    source_id = "arxiv"
    needs_key = False
    rate_limit_per_sec = 1.0

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            q = query.query_string or "AI technology"
            n = min(query.limit, 100)
            params = {
                "search_query": q,
                "start": 0,
                "max_results": n,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
            resp = self._http_get("https://export.arxiv.org/api/query", params=params)

            root = ET.fromstring(resp.text)
            entries = root.findall(f"{{{ATOM_NS}}}entry")

            docs = []
            for entry in entries:
                id_elem = entry.find(f"{{{ATOM_NS}}}id")
                title_elem = entry.find(f"{{{ATOM_NS}}}title")
                summary_elem = entry.find(f"{{{ATOM_NS}}}summary")
                published_elem = entry.find(f"{{{ATOM_NS}}}published")

                id_text = id_elem.text or "" if id_elem is not None else ""
                title = title_elem.text or "" if title_elem is not None else ""
                summary = summary_elem.text or "" if summary_elem is not None else ""
                published_str = published_elem.text or "" if published_elem is not None else ""

                published_at: Optional[datetime] = None
                if published_str:
                    try:
                        published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                    except ValueError:
                        published_at = None

                authors = [
                    a.find(f"{{{ATOM_NS}}}name").text
                    for a in entry.findall(f"{{{ATOM_NS}}}author")
                    if a.find(f"{{{ATOM_NS}}}name") is not None
                ]

                categories = [
                    c.get("term", "")
                    for c in entry.findall("{http://arxiv.org/schemas/atom}primary_category")
                ] + [
                    c.get("term", "")
                    for c in entry.findall("{http://arxiv.org/schemas/atom}category")
                ]

                link_elem = entry.find(f"{{{ATOM_NS}}}link[@rel='alternate']")
                if link_elem is None:
                    link_elem = entry.find(f"{{{ATOM_NS}}}link")
                url = link_elem.get("href", "") if link_elem is not None else id_text

                arxiv_id = id_text.split("/")[-1] if "/" in id_text else id_text
                content_hash = self._content_hash(arxiv_id)

                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=arxiv_id,
                    url=url,
                    content_hash=content_hash,
                    doc_type="paper",
                    title=title.strip(),
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "arxiv_id": arxiv_id,
                        "summary": summary[:500],
                        "authors": authors[:5],
                        "categories": categories,
                    },
                    summary=summary[:300],
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
