from __future__ import annotations
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "raw" / "ticker_resolver"
COMPANY_TICKERS_PATH = ROOT / "data" / "raw" / "sec_edgar" / "company_tickers.json"
CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days

logger = logging.getLogger("visionairy2.ingestion.ticker_resolver")


class TickerResolver:
    def __init__(self, db_session_factory: Any, llm_client: Any) -> None:
        self._db_session_factory = db_session_factory
        self._llm = llm_client
        self._sec_tickers: Optional[dict] = None

    def resolve(self, name: str) -> Optional[str]:
        if not name or not name.strip():
            return None

        cache_path = CACHE_DIR / f"{hashlib.sha256(name.lower().encode()).hexdigest()}.json"
        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < CACHE_TTL_SECONDS:
                try:
                    return json.loads(cache_path.read_text()).get("ticker")
                except Exception:
                    pass

        ticker = (
            self._resolve_db(name)
            or self._resolve_sec(name)
            or self._resolve_fmp(name)
            or self._resolve_wikidata(name)
            or self._resolve_llm(name)
        )

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"name": name, "ticker": ticker}))

        if ticker and self._db_session_factory:
            self._upsert_company(name, ticker)

        return ticker

    def _resolve_db(self, name: str) -> Optional[str]:
        if not self._db_session_factory:
            return None
        try:
            from src.storage.models import Company
            with self._db_session_factory() as session:
                row = session.query(Company).filter(
                    Company.name.ilike(name)
                ).first()
                return row.ticker if row and row.ticker else None
        except Exception:
            return None

    def _resolve_sec(self, name: str) -> Optional[str]:
        try:
            tickers = self._load_sec_tickers()
            name_lower = name.lower().strip()
            for entry in tickers.values():
                if entry.get("title", "").lower() == name_lower:
                    return entry.get("ticker", "").upper() or None
        except Exception:
            pass
        return None

    def _load_sec_tickers(self) -> dict:
        if self._sec_tickers is not None:
            return self._sec_tickers
        # Refresh weekly
        if COMPANY_TICKERS_PATH.exists():
            age = time.time() - COMPANY_TICKERS_PATH.stat().st_mtime
            if age < 7 * 24 * 3600:
                try:
                    self._sec_tickers = json.loads(COMPANY_TICKERS_PATH.read_text())
                    return self._sec_tickers
                except Exception:
                    pass
        resp = httpx.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": os.environ.get("SEC_USER_AGENT", "VisionAiry2 projectgemini53@gmail.com")},
            timeout=15.0,
        )
        if resp.status_code == 200:
            COMPANY_TICKERS_PATH.parent.mkdir(parents=True, exist_ok=True)
            COMPANY_TICKERS_PATH.write_text(resp.text)
            self._sec_tickers = resp.json()
        else:
            self._sec_tickers = {}
        return self._sec_tickers

    def _resolve_fmp(self, name: str) -> Optional[str]:
        fmp_key = os.environ.get("FMP_API_KEY", "")
        if not fmp_key:
            return None
        try:
            resp = httpx.get(
                "https://financialmodelingprep.com/api/v3/search",
                params={"query": name, "limit": 5, "apikey": fmp_key},
                timeout=10.0,
            )
            if resp.status_code == 200:
                results = resp.json()
                if isinstance(results, list) and results:
                    return results[0].get("symbol", "").upper() or None
        except Exception:
            pass
        return None

    def _resolve_wikidata(self, name: str) -> Optional[str]:
        try:
            resp = httpx.get(
                "https://www.wikidata.org/w/api.php",
                params={"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "type": "item", "limit": 3},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            results = resp.json().get("search", [])
            for item in results:
                qid = item.get("id", "")
                if not qid:
                    continue
                # Fetch entity claims for P249 (ticker)
                entity_resp = httpx.get(
                    "https://www.wikidata.org/w/api.php",
                    params={"action": "wbgetclaims", "entity": qid, "property": "P249", "format": "json"},
                    timeout=10.0,
                )
                if entity_resp.status_code == 200:
                    claims = entity_resp.json().get("claims", {}).get("P249", [])
                    for claim in claims:
                        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", "")
                        if v:
                            return v.upper()
        except Exception:
            pass
        return None

    def _resolve_llm(self, name: str) -> Optional[str]:
        try:
            resp = self._llm.complete(
                role="entity_extraction",
                system=(
                    "You are a financial data expert. Given a company name, return ONLY the stock ticker symbol "
                    "(e.g. AAPL, NVDA, TSLA) for the most likely publicly traded company with that name. "
                    "If not publicly traded or unknown, return null. "
                    'Respond in JSON: {"ticker": "SYMB" or null}'
                ),
                user=f"Company name: {name}",
                max_tokens=32,
                agent_name="ticker_resolver_llm",
            )
            import re
            cleaned = re.sub(r"```[a-z]*\n?", "", resp.strip()).strip("`").strip()
            data = json.loads(cleaned)
            t = data.get("ticker")
            return t.upper() if t and isinstance(t, str) else None
        except Exception:
            return None

    def _upsert_company(self, name: str, ticker: str) -> None:
        try:
            from src.storage.models import Company, _ulid
            with self._db_session_factory() as session:
                existing = session.query(Company).filter_by(ticker=ticker.upper()).first()
                if not existing:
                    row = Company(
                        id=_ulid(),
                        name=name,
                        ticker=ticker.upper(),
                        sector_id="unknown",
                        is_public=True,
                    )
                    session.add(row)
                    session.commit()
        except Exception as exc:
            logger.debug("Company upsert failed: %s", exc)
