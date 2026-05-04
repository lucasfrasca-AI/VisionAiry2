"""USASpending.gov — sector_routed=True (defence + AI)."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class USASpendingClient(BaseSourceClient):
    source_id = "usaspending"
    needs_key = False
    rate_limit_per_sec = 2.0
    sector_routed = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            lookback = query.lookback_days or 30
            today = date.today()
            from_date = (today - timedelta(days=lookback)).isoformat()

            keywords = query.extra.get("keywords", [])
            if not keywords and query.query_string:
                keywords = [query.query_string]
            elif not keywords:
                keywords = ["defense", "artificial intelligence"]

            body: dict[str, Any] = {
                "filters": {
                    "award_type_codes": ["A", "B", "C", "D"],
                    "time_period": [{"start_date": from_date, "end_date": today.isoformat()}],
                    "keywords": keywords,
                },
                "fields": [
                    "Award ID",
                    "Recipient Name",
                    "Award Amount",
                    "Start Date",
                    "End Date",
                    "Description",
                    "Awarding Agency",
                ],
                "page": 1,
                "limit": min(query.limit, 50),
                "sort": "Award Amount",
                "order": "desc",
            }

            resp = self._http_post(
                "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                json=body,
            )
            data = resp.json()

            awards = data.get("results", [])
            docs = []
            for award in awards:
                award_id = award.get("Award ID", "")
                title = f"{award.get('Recipient Name', '')} - {award.get('Description', '')[:80]}"
                amount = award.get("Award Amount", 0)
                start = award.get("Start Date", "")

                published_at: Optional[datetime] = None
                try:
                    if start:
                        published_at = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except Exception:
                    published_at = None

                content_hash = self._content_hash(award_id + str(amount))
                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=award_id,
                    url=f"https://www.usaspending.gov/award/{award_id}/" if award_id else "",
                    content_hash=content_hash,
                    doc_type="contract",
                    title=title[:200],
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload=award,
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
