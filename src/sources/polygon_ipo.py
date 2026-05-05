"""Polygon.io IPO calendar client — emerging-signal source."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError,
)

_SPAC_NAME_PATTERNS = ("acquisition corp", "acquisition corporation")
_SPAC_SEC_PATTERNS = ("units",)


def _is_spac(record: dict) -> bool:
    name = (record.get("issuer_name") or "").lower()
    sec = (record.get("security_description") or "").lower()
    if any(p in name for p in _SPAC_NAME_PATTERNS):
        return True
    if any(p in sec for p in _SPAC_SEC_PATTERNS):
        return True
    return False


class PolygonIPOClient(BaseSourceClient):
    source_id = "polygon_ipo"
    needs_key = True
    key_env_var = "POLYGON_API_KEY"
    rate_limit_per_sec = 0.083  # 5/min free tier
    cache_ttl_seconds = 14400   # 4 hours
    emerging_signal = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()
        cached = self._cached(query)
        if cached:
            return cached

        key = os.environ.get("POLYGON_API_KEY", "")
        now = datetime.now(timezone.utc)
        d_from = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        d_to = (now + timedelta(days=90)).strftime("%Y-%m-%d")

        docs: list[SourceDocument] = []
        errors: list[str] = []
        fetched_at = self._utcnow()

        for status in ("pending", "priced"):
            ipo_status_filter = query.extra.get("ipo_status", status)
            if query.extra.get("ipo_status") and ipo_status_filter != status:
                continue
            params = {
                "apiKey": key,
                "order": "desc",
                "limit": 50,
                "sort": "listing_date",
                "ipo_status": status,
                "listing_date.gte": d_from,
                "listing_date.lte": d_to,
            }
            try:
                resp = self._http_get("https://api.polygon.io/vX/reference/ipos", params=params)
                data = resp.json()
            except (SourceAuthError, SourceRateLimitError):
                raise
            except Exception as exc:
                errors.append(f"polygon_ipo {status}: {exc}")
                continue

            for record in data.get("results", []):
                if _is_spac(record):
                    continue

                ticker = record.get("ticker") or ""
                issuer = record.get("issuer_name") or ""
                exchange = record.get("primary_exchange") or ""
                announced = record.get("announced_date") or ""
                ipo_status = record.get("ipo_status") or ""
                sec_desc = record.get("security_description") or ""
                low_price = record.get("lowest_offer_price")
                high_price = record.get("highest_offer_price")
                max_shares = record.get("max_shares_offered") or 0
                total_offer = record.get("total_offer_size") or 0
                last_updated = record.get("last_updated") or ""

                price_range = (
                    f"${low_price}-{high_price}"
                    if low_price and high_price
                    else (f"${low_price}" if low_price else "price TBD")
                )
                source_id = ticker or self._content_hash((issuer or "") + (announced or ""))[:16]
                url = (
                    f"https://www.polygon.io/quote/{ticker}"
                    if ticker
                    else f"https://www.sec.gov/cgi-bin/browse-edgar?company={issuer[:40]}&action=getcompany"
                )

                published_at: Optional[datetime] = None
                if last_updated:
                    try:
                        published_at = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                summary_parts = [
                    f"Status: {ipo_status}.",
                    f"Announced: {announced}." if announced else "",
                    f"Max shares: {int(max_shares):,}." if max_shares else "",
                    f"Total offering: ${float(total_offer):,.0f}." if total_offer else "",
                    f"Security: {sec_desc}." if sec_desc else "",
                ]
                summary = " ".join(p for p in summary_parts if p)

                docs.append(SourceDocument(
                    source=self.source_id,
                    source_id=source_id,
                    url=url,
                    content_hash=self._content_hash(source_id),
                    doc_type="filing",
                    title=f"IPO {ipo_status}: {issuer} ({ticker or 'TBD'}, {exchange}, {price_range})",
                    published_at=published_at,
                    fetched_at=fetched_at,
                    raw_payload=record,
                    summary=summary,
                    entities_mentioned=[issuer] if issuer else [],
                ))

            # Only filter by single status if caller passed it explicitly
            if query.extra.get("ipo_status"):
                break

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=docs,
            fetched_at=fetched_at,
            errors=errors,
        )
        self._cache(query, result)
        return result
