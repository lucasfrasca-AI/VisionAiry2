"""SEC company_tickers.json delta tracker — surfaces newly-registered tickers."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

from src.sources.base import (
    BaseSourceClient, SourceDocument, SourceQuery, SourceResult,
)

_SNAPSHOT_DIR = Path("data/raw/sec_tickers")


class SECTickersDeltaClient(BaseSourceClient):
    source_id = "sec_tickers_delta"
    needs_key = False
    rate_limit_per_sec = 1.0
    emerging_signal = True

    def _sec_headers(self) -> dict:
        return {"User-Agent": os.environ.get("SEC_USER_AGENT", "VisionAiry2 projectgemini53@gmail.com")}

    def _snapshot_path(self, for_date: date) -> Path:
        return _SNAPSHOT_DIR / f"company_tickers_{for_date.isoformat()}.json"

    def _load_snapshot(self, path: Path) -> dict[str, dict]:
        """Load snapshot; returns {ticker: {cik, name}} mapping."""
        try:
            raw = json.loads(path.read_text())
            result: dict[str, dict] = {}
            for _idx, entry in raw.items():
                ticker = entry.get("ticker") or ""
                cik = str(entry.get("cik_str") or entry.get("cik") or "")
                name = entry.get("title") or entry.get("name") or ""
                if ticker:
                    result[ticker] = {"cik": cik, "name": name}
            return result
        except Exception:
            return {}

    def _find_old_snapshot(self, today: date, delta_days: int = 30) -> Optional[Path]:
        """Find the most recent snapshot that is at least delta_days old."""
        if not _SNAPSHOT_DIR.exists():
            return None
        candidates = sorted(_SNAPSHOT_DIR.glob("company_tickers_*.json"))
        for path in reversed(candidates):
            stem = path.stem  # company_tickers_2025-01-01
            date_str = stem.replace("company_tickers_", "")
            try:
                snap_date = date.fromisoformat(date_str)
                if (today - snap_date).days >= delta_days:
                    return path
            except ValueError:
                continue
        return None

    def fetch(self, query: SourceQuery) -> SourceResult:
        cached = self._cached(query)
        if cached:
            return cached

        fetched_at = self._utcnow()
        today = date.today()
        today_path = self._snapshot_path(today)
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

        # Fetch today's snapshot if not already saved
        if not today_path.exists():
            try:
                resp = self._http_get(
                    "https://www.sec.gov/files/company_tickers.json",
                    headers=self._sec_headers(),
                )
                today_path.write_text(resp.text)
            except Exception as exc:
                return SourceResult(
                    source=self.source_id,
                    query=query,
                    documents=[],
                    fetched_at=fetched_at,
                    errors=[f"SEC tickers fetch failed: {exc}"],
                )

        old_path = self._find_old_snapshot(today, delta_days=30)
        if old_path is None:
            result = SourceResult(
                source=self.source_id,
                query=query,
                documents=[],
                fetched_at=fetched_at,
                errors=["No historical snapshot for delta. Run scans periodically to build delta history."],
            )
            self._cache(query, result)
            return result

        today_map = self._load_snapshot(today_path)
        old_map = self._load_snapshot(old_path)
        old_date_str = old_path.stem.replace("company_tickers_", "")

        new_tickers = set(today_map.keys()) - set(old_map.keys())
        docs: list[SourceDocument] = []

        for ticker in sorted(new_tickers)[: query.limit]:
            entry = today_map[ticker]
            cik = entry["cik"]
            name = entry["name"]
            source_id = self._content_hash(ticker + cik)[:16]
            url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
                if cik else ""
            )
            docs.append(SourceDocument(
                source=self.source_id,
                source_id=source_id,
                url=url,
                content_hash=self._content_hash(source_id),
                doc_type="filing",
                title=f"New SEC registrant: {name} ({ticker}, CIK={cik})",
                published_at=datetime.now(timezone.utc),
                fetched_at=fetched_at,
                raw_payload={"ticker": ticker, "cik": cik, "name": name},
                summary=(
                    f"This ticker first appeared in SEC's company_tickers.json "
                    f"between {old_date_str} and {today.isoformat()}."
                ),
                entities_mentioned=[name] if name else [ticker],
            ))

        result = SourceResult(
            source=self.source_id,
            query=query,
            documents=docs,
            fetched_at=fetched_at,
        )
        self._cache(query, result)
        return result
