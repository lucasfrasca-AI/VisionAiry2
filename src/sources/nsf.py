"""NSF Awards API client — non-academic company grants as emerging-company signal."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
from typing import Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
)

_ACADEMIC_PATTERNS = (
    "university", "college", "institute of technology", "school of",
    "academy", "trustees", "regents", "suny", "state university",
    "research foundation", "community college",
)


def _is_academic(name: str) -> bool:
    low = name.lower()
    return any(p in low for p in _ACADEMIC_PATTERNS)


class NSFAwardsClient(BaseSourceClient):
    source_id = "nsf_awards"
    needs_key = False
    rate_limit_per_sec = 2.0
    sector_routed = True
    emerging_signal = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached:
            return cached

        keyword = query.query_string or "technology"
        lookback = query.lookback_days or 180
        today = date.today()
        start = today - timedelta(days=lookback)
        # NSF uses MM/DD/YYYY format
        date_start = start.strftime("%m/%d/%Y")
        date_end = today.strftime("%m/%d/%Y")

        params = {
            "keyword": keyword,
            "dateStart": date_start,
            "dateEnd": date_end,
            "rpp": 25,
        }

        fetched_at = self._utcnow()
        try:
            resp = self._http_get(
                "https://api.nsf.gov/services/v1/awards.json",
                params=params,
                headers={"User-Agent": "VisionAiry2"},
            )
            data = resp.json()
        except Exception as exc:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=fetched_at,
                errors=[f"NSF API note: {exc}"],
            )

        awards = data.get("response", {}).get("award", [])
        if not isinstance(awards, list):
            awards = []

        docs: list[SourceDocument] = []
        for award in awards[: query.limit]:
            awardee = (award.get("awardeeName") or "").strip()
            if not awardee or _is_academic(awardee):
                continue

            award_id = str(award.get("id") or "")
            instrument = award.get("awardInstrument") or ""
            funds_raw = award.get("fundsObligatedAmt") or 0
            try:
                funds = float(str(funds_raw).replace(",", "")) if funds_raw else 0.0
            except ValueError:
                funds = 0.0

            abstract = (award.get("abstractText") or "")[:1000]
            start_date_str = award.get("startDate") or ""
            published_at: Optional[datetime] = None
            if start_date_str:
                try:
                    published_at = datetime.strptime(start_date_str[:10], "%m/%d/%Y").replace(tzinfo=timezone.utc)
                except ValueError:
                    try:
                        published_at = datetime.strptime(start_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass

            source_id = award_id or self._content_hash(awardee + instrument)[:16]
            url = f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={award_id}" if award_id else ""

            docs.append(SourceDocument(
                source=self.source_id,
                source_id=source_id,
                url=url,
                content_hash=self._content_hash(source_id),
                doc_type="grant",
                title=f"{awardee} — NSF {instrument} (${funds:,.0f})",
                published_at=published_at,
                fetched_at=fetched_at,
                raw_payload=award,
                summary=abstract,
                entities_mentioned=[awardee],
            ))

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=docs,
            fetched_at=fetched_at,
        )
        self._cache(query, result)
        return result
