from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date

from src.sources.base import (
    BaseSourceClient,
    SourceDocument,
    SourceQuery,
    SourceResult,
    SourceAuthError,
    SourceRateLimitError,
)


class EdgarClient(BaseSourceClient):
    source_id = "edgar"
    needs_key = False
    key_env_var = None
    rate_limit_per_sec = 8.0

    def __init__(self, config, db_session_factory=None) -> None:
        super().__init__(config, db_session_factory)
        from edgar import set_identity
        set_identity(os.environ.get("SEC_USER_AGENT", "VisionAiry2 projectgemini53@gmail.com"))

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached:
            return cached

        ticker = query.ticker or ""
        mode = query.extra.get("mode", "recent_filings")
        fetched_at = self._utcnow()
        docs: list[SourceDocument] = []

        try:
            if mode == "recent_filings":
                from edgar import Company
                company = Company(ticker)
                form_types = query.extra.get("form_types", ["8-K", "10-K", "10-Q", "13F-HR"])
                per_type = max(1, query.limit // len(form_types) + 1)
                all_filings = []
                for form_type in form_types:
                    try:
                        filings = company.get_filings(form=form_type).latest(n=per_type)
                        if filings is None:
                            continue
                        if hasattr(filings, "__iter__"):
                            all_filings.extend(list(filings))
                        else:
                            all_filings.append(filings)
                    except Exception:
                        continue

                for filing in all_filings[: query.limit]:
                    accession = getattr(filing, "accession_number", None) or ""
                    filing_date = getattr(filing, "filing_date", None)
                    form = getattr(filing, "form", "")
                    published_at = None
                    if filing_date:
                        published_at = datetime.combine(
                            filing_date, datetime.min.time()
                        ).replace(tzinfo=timezone.utc)
                    url = (
                        f"https://www.sec.gov/Archives/edgar/{accession.replace('-', '/')}"
                        if accession
                        else ""
                    )
                    raw_payload = {
                        "form": form,
                        "accession_number": accession,
                        "filing_date": str(filing_date),
                    }
                    content_hash = self._content_hash(accession or str(raw_payload))
                    docs.append(
                        SourceDocument(
                            source=self.source_id,
                            source_id=accession,
                            url=url,
                            content_hash=content_hash,
                            doc_type="filing",
                            title=f"{form} {ticker} {filing_date}",
                            published_at=published_at,
                            fetched_at=fetched_at,
                            raw_payload=raw_payload,
                        )
                    )

            elif mode == "form_d_scan":
                from edgar import get_filings
                lookback = query.lookback_days or 14
                today = date.today()
                start = today - timedelta(days=lookback)
                filings_list = get_filings(
                    form="D",
                    date=(start.isoformat(), today.isoformat()),
                )
                count = min(query.limit, 50)
                items = list(filings_list)[:count] if filings_list else []
                for filing in items:
                    accession = getattr(filing, "accession_number", None) or ""
                    filing_date = getattr(filing, "filing_date", None)
                    form = getattr(filing, "form", "D")
                    published_at = None
                    if filing_date:
                        published_at = datetime.combine(
                            filing_date, datetime.min.time()
                        ).replace(tzinfo=timezone.utc)
                    url = (
                        f"https://www.sec.gov/Archives/edgar/{accession.replace('-', '/')}"
                        if accession
                        else ""
                    )
                    raw_payload = {
                        "form": form,
                        "accession_number": accession,
                        "filing_date": str(filing_date),
                    }
                    content_hash = self._content_hash(accession or str(raw_payload))
                    docs.append(
                        SourceDocument(
                            source=self.source_id,
                            source_id=accession,
                            url=url,
                            content_hash=content_hash,
                            doc_type="filing",
                            title=f"D {filing_date}",
                            published_at=published_at,
                            fetched_at=fetched_at,
                            raw_payload=raw_payload,
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
