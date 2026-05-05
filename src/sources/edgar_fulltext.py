"""SEC EDGAR full-text search client — S-1/IPO filings for emerging companies."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError,
)

_DEFAULT_FORMS = "S-1,S-1/A,F-1,F-1/A,DRS"


class EdgarFullTextClient(BaseSourceClient):
    source_id = "edgar_fulltext"
    needs_key = False
    rate_limit_per_sec = 8.0
    emerging_signal = True

    def _sec_headers(self) -> dict:
        return {"User-Agent": os.environ.get("SEC_USER_AGENT", "VisionAiry2 projectgemini53@gmail.com")}

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached:
            return cached

        lookback = query.lookback_days or 90
        today = date.today()
        start_dt = (today - timedelta(days=lookback)).isoformat()
        end_dt = today.isoformat()
        keyword = query.query_string or "technology"
        forms = query.extra.get("forms", _DEFAULT_FORMS)

        params = {
            "q": keyword,
            "dateRange": "custom",
            "startdt": start_dt,
            "enddt": end_dt,
            "forms": forms,
        }

        fetched_at = self._utcnow()
        try:
            resp = self._http_get(
                "https://efts.sec.gov/LATEST/search-index",
                params=params,
                headers=self._sec_headers(),
            )
            data = resp.json()
        except (SourceAuthError, SourceRateLimitError):
            raise
        except Exception as exc:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=fetched_at,
                errors=[f"EDGAR full-text search error: {exc}"],
            )

        hits = data.get("hits", {}).get("hits", [])
        docs: list[SourceDocument] = []

        for hit in hits[: query.limit]:
            src = hit.get("_source", {})
            accession_raw = src.get("file_date", "") + src.get("entity_name", "")
            accession = src.get("accession_no") or self._content_hash(accession_raw)[:16]
            company_name = src.get("entity_name") or src.get("display_names", [""])[0] if src.get("display_names") else ""
            form_type = src.get("form_type") or src.get("file_type") or "S-1"
            filed_date = src.get("file_date") or src.get("period_of_report") or ""
            description = src.get("period_of_report") or ""

            published_at: Optional[datetime] = None
            if filed_date:
                try:
                    published_at = datetime.strptime(filed_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            # Build SEC filing URL from accession number
            accession_clean = accession.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{src.get('entity_id', '')}/{accession_clean}/"
                if src.get("entity_id") and len(accession_clean) > 10
                else f"https://efts.sec.gov/LATEST/search-index?q={keyword}&forms={forms}"
            )

            summary_text = (
                f"Form {form_type} filed {filed_date}. "
                + (f"Description: {description[:200]}" if description else "")
            )

            docs.append(SourceDocument(
                source=self.source_id,
                source_id=accession[:32],
                url=url,
                content_hash=self._content_hash(accession),
                doc_type="filing",
                title=f"{form_type}: {company_name} ({filed_date})" if company_name else f"{form_type} filing ({filed_date})",
                published_at=published_at,
                fetched_at=fetched_at,
                raw_payload=src,
                summary=summary_text,
                entities_mentioned=[company_name] if company_name else [],
            ))

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=docs,
            fetched_at=fetched_at,
        )
        self._cache(query, result)
        return result
