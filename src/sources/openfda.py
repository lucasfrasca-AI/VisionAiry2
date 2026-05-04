"""OpenFDA client — sector_routed=True (pharma/biotech only)."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
    SourceAuthError, SourceRateLimitError, SourceUnavailableError,
)


def _parse_fda_date(s: str, endpoint: str) -> Optional[datetime]:
    """Parse FDA date strings. Events use YYYYMMDD; enforcement/label use ISO-like formats."""
    if not s:
        return None
    if endpoint == "event":
        try:
            return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    else:
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


class OpenFdaClient(BaseSourceClient):
    source_id = "openfda"
    needs_key = True
    key_env_var = "OPENFDA_API_KEY"
    rate_limit_per_sec = 4.0
    sector_routed = True

    def fetch(self, query: SourceQuery) -> SourceResult:
        self._guard_available()

        cached = self._cached(query)
        if cached:
            return cached

        endpoint = query.extra.get("endpoint", "event")
        q = query.query_string or query.ticker or ""
        n = min(query.limit, 20)
        key = os.environ.get("OPENFDA_API_KEY", "")

        endpoint_map = {
            "event": "https://api.fda.gov/drug/event.json",
            "enforcement": "https://api.fda.gov/drug/enforcement.json",
            "label": "https://api.fda.gov/drug/label.json",
        }
        base_url = endpoint_map.get(endpoint, endpoint_map["event"])

        params: dict[str, Any] = {"limit": n, "api_key": key}
        if q:
            params["search"] = q

        try:
            resp = self._http_get(base_url, params=params)
            data = resp.json()
        except (SourceAuthError, SourceRateLimitError):
            raise
        except Exception as exc:
            return SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=self._utcnow(),
                errors=[str(exc)],
            )

        documents: list[SourceDocument] = []
        for result in data.get("results", []):
            safety_id = str(result.get("safetyreportid", ""))

            content_hash = self._content_hash(
                endpoint + safety_id + str(result.get("event_date_terminated", ""))
            )
            src_id = safety_id if safety_id else content_hash[:16]

            if endpoint == "event":
                title = (
                    result.get("patient", {})
                    .get("drug", [{}])[0]
                    .get("medicinalproduct", "FDA event")
                )
                date_str = result.get("receivedate", "")
                published_at = _parse_fda_date(date_str, "event")
            elif endpoint == "enforcement":
                title = result.get("product_description", "FDA enforcement")[:100]
                date_str = result.get("recall_initiation_date", "")
                published_at = _parse_fda_date(date_str, "enforcement")
            else:
                # label
                openfda = result.get("openfda", {})
                brand_names = openfda.get("brand_name", ["FDA label"])
                title = brand_names[0] if brand_names else "FDA label"
                date_str = result.get("effective_time", "")
                published_at = _parse_fda_date(date_str, "label")

            documents.append(
                SourceDocument(
                    source=self.source_id,
                    source_id=src_id,
                    url="",
                    content_hash=content_hash,
                    doc_type="filing",
                    title=title,
                    published_at=published_at,
                    fetched_at=self._utcnow(),
                    raw_payload=result,
                )
            )

        result_obj = SourceResult(
            source=self.source_id,
            query=query,
            documents=documents,
            fetched_at=self._utcnow(),
        )
        self._cache(query, result_obj)
        return result_obj
