"""ClinicalTrials.gov v2 API — sector_routed=True (pharma/biotech)."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


class ClinicalTrialsClient(BaseSourceClient):
    source_id = "clinicaltrials"
    needs_key = False
    rate_limit_per_sec = 5.0
    sector_routed = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached is not None:
            return cached

        try:
            q = query.query_string or query.ticker or "cancer"
            n = min(query.limit, 100)
            params: dict[str, Any] = {
                "query.term": q,
                "pageSize": n,
                "format": "json",
            }

            resp = self._http_get("https://clinicaltrials.gov/api/v2/studies", params=params)
            data = resp.json()

            studies = data.get("studies", [])
            docs = []
            for study in studies:
                pm = study.get("protocolSection", {})
                id_mod = pm.get("identificationModule", {})
                nct_id = id_mod.get("nctId", "")
                brief_title = id_mod.get("briefTitle", "")
                status_mod = pm.get("statusModule", {})
                start_date_str = status_mod.get("startDateStruct", {}).get("date", "")

                published_at: Optional[datetime] = None
                try:
                    if start_date_str:
                        published_at = datetime.strptime(start_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except Exception:
                    published_at = None

                content_hash = self._content_hash(nct_id)
                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=nct_id,
                    url=f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "",
                    content_hash=content_hash,
                    doc_type="filing",
                    title=brief_title,
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload={
                        "nct_id": nct_id,
                        "overall_status": status_mod.get("overallStatus", ""),
                        "phase": pm.get("designModule", {}).get("phases", []),
                    },
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
