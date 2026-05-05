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
    emerging_signal = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        endpoint = query.extra.get("endpoint", "prime_awards")
        if endpoint == "subawards":
            return self._fetch_subawards(query)

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

    _NON_COMPANY_PATTERNS = (
        "town of ", "city of ", "county of ", "county,", " county",
        "state of ", "department of ", "board of ", "government of ",
        "public school", "school district",
        "research foundation for the state", "university", "college",
        "institute of technology", "family & community", "community services",
        "health services", "social services", "community health", "medical center",
        "hospital", "church", "diocese",
    )

    def _is_non_company(self, name: str) -> bool:
        low = name.lower()
        return any(p in low for p in self._NON_COMPANY_PATTERNS)

    def _fetch_subawards(self, query: SourceQuery) -> SourceResult:
        fetched_at = self._utcnow()
        try:
            lookback = query.lookback_days or 90
            today = date.today()
            d1 = (today - timedelta(days=lookback)).isoformat()
            keywords = query.extra.get("keywords", [])
            if not keywords and query.query_string:
                keywords = [query.query_string]
            elif not keywords:
                keywords = ["technology", "artificial intelligence"]

            body: dict[str, Any] = {
                "filters": {
                    "keywords": keywords,
                    "time_period": [{"start_date": d1, "end_date": today.isoformat()}],
                    "award_type_codes": ["A", "B", "C", "D"],
                },
                "page": 1,
                "limit": min(query.limit, 50),
                "sort": "amount",
                "order": "desc",
            }
            resp = self._http_post(
                "https://api.usaspending.gov/api/v2/subawards/",
                json=body,
            )
            data = resp.json()
            awards = data.get("results", [])
            docs: list[SourceDocument] = []
            for award in awards:
                recipient = (award.get("recipient_name") or award.get("subawardee_name") or "").strip()
                if not recipient or self._is_non_company(recipient):
                    continue
                prime = award.get("prime_award_recipient") or award.get("prime_recipient_name") or ""
                sub_num = award.get("subaward_number") or award.get("sub_award_number") or ""
                amount_raw = award.get("amount") or award.get("subaward_amount") or 0
                try:
                    amount = float(str(amount_raw).replace(",", "")) if amount_raw else 0.0
                    if amount > 1e12:  # guard against corrupted API data
                        amount = 0.0
                except ValueError:
                    amount = 0.0
                description = (award.get("description") or "")[:500]
                source_id = sub_num or self._content_hash(recipient + str(amount))[:16]
                url = (
                    f"https://www.usaspending.gov/award/{sub_num}/"
                    if sub_num else ""
                )
                keyword_ctx = f"Contract keywords: {', '.join(keywords)}. " if keywords else ""
                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=source_id,
                    url=url,
                    content_hash=self._content_hash(source_id),
                    doc_type="contract",
                    title=f"Subaward: {recipient} <- {prime} (${amount:,.0f})"[:200],
                    published_at=None,
                    fetched_at=fetched_at,
                    raw_payload=award,
                    summary=(keyword_ctx + description)[:600],
                    entities_mentioned=[recipient],
                ))
            result = SourceResult(
                source=self.source_id,
                query=query,
                documents=docs,
                fetched_at=fetched_at,
            )
            self._cache(query, result)
            return result
        except Exception as exc:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=fetched_at,
                errors=[str(exc)],
            )
