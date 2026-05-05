"""SBIR/STTR awards client — US government-validated emerging companies."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
)


class SBIRClient(BaseSourceClient):
    source_id = "sbir"
    needs_key = False
    rate_limit_per_sec = 2.0
    sector_routed = True
    emerging_signal = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached:
            return cached

        keyword = query.query_string or query.ticker or "artificial intelligence"
        lookback = query.lookback_days or 180
        start_date = (date.today() - timedelta(days=lookback)).strftime("%Y-%m-%d")
        # Try primary endpoint first, fall back to alternative
        endpoints = [
            ("https://www.sbir.gov/api/awards.json",
             {"keyword": keyword, "start_date": start_date, "rows": 100}),
            ("https://www.sbir.gov/api/solicitations.json",
             {"keyword": keyword, "start_date": start_date, "rows": 100}),
        ]

        fetched_at = self._utcnow()
        try:
            resp = None
            for url, params in endpoints:
                try:
                    resp = self._http_get(url, params=params)
                    break
                except Exception:
                    continue
            if resp is None:
                raise RuntimeError("All SBIR API endpoints returned errors")
            try:
                awards = resp.json()
            except Exception:
                awards = json.loads(resp.text.strip())
        except Exception as exc:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=fetched_at,
                errors=[f"SBIR API error: {exc}"],
            )

        if not isinstance(awards, list):
            awards = awards.get("results", []) if isinstance(awards, dict) else []

        docs: list[SourceDocument] = []
        for award in awards[: query.limit]:
            firm = (award.get("firm") or "").strip()
            if not firm:
                continue

            award_id = str(award.get("award_id") or "")
            uei = award.get("uei") or ""
            source_id = uei or award_id or self._content_hash(
                firm + str(award.get("award_year", "")) + str(award.get("agency", ""))
            )[:16]

            amount_raw = award.get("award_amount", 0)
            try:
                amount = float(str(amount_raw).replace(",", "").replace("$", "")) if amount_raw else 0.0
            except ValueError:
                amount = 0.0

            phase = award.get("phase") or ""
            agency = award.get("agency") or ""
            year = str(award.get("award_year") or "")
            abstract = (award.get("abstract") or "")[:1000]

            published_at: Optional[datetime] = None
            if year:
                try:
                    published_at = datetime(int(year), 1, 1, tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass

            slug = firm.lower().replace(" ", "_").replace(",", "")[:30]
            url = f"https://www.sbir.gov/sbirsearch/firm/{slug}" if firm else ""
            if award_id:
                url = f"https://www.sbir.gov/sbirsearch/detail/{award_id}"

            docs.append(SourceDocument(
                source=self.source_id,
                source_id=source_id,
                url=url,
                content_hash=self._content_hash(source_id),
                doc_type="grant",
                title=f"{firm} — SBIR {phase} ({agency}, ${amount:,.0f})",
                published_at=published_at,
                fetched_at=fetched_at,
                raw_payload=award,
                summary=abstract,
                entities_mentioned=[firm],
            ))

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=docs,
            fetched_at=fetched_at,
        )
        self._cache(query, result)
        return result
