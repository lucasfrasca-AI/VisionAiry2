"""Live price and market data service for the VisionAiry2 dashboard."""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("visionairy2.dashboard.live_data")

_CACHE_TTL_SECS = 60
_STALE_AFTER_SECS = 300


class LivePriceService:
    """Fetch live price snapshots with in-memory 60-second cache."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, dict]] = {}  # ticker -> (timestamp, snapshot)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_snapshot(self, ticker: str) -> dict | None:
        cached_ts, cached_data = self._cache.get(ticker, (0.0, {}))
        if cached_data and (time.monotonic() - cached_ts) < _CACHE_TTL_SECS:
            return cached_data
        snap = self._fetch(ticker)
        if snap:
            self._cache[ticker] = (time.monotonic(), snap)
        return snap

    def get_snapshots_bulk(self, tickers: list[str]) -> dict[str, dict | None]:
        fresh: dict[str, dict | None] = {}
        to_fetch: list[str] = []
        now = time.monotonic()

        for t in tickers:
            cached_ts, cached_data = self._cache.get(t, (0.0, {}))
            if cached_data and (now - cached_ts) < _CACHE_TTL_SECS:
                fresh[t] = cached_data
            else:
                to_fetch.append(t)

        if to_fetch:
            with ThreadPoolExecutor(max_workers=10) as pool:
                fut_map = {pool.submit(self._fetch, t): t for t in to_fetch}
                for fut in as_completed(fut_map, timeout=30):
                    ticker = fut_map[fut]
                    try:
                        snap = fut.result(timeout=10)
                        if snap:
                            self._cache[ticker] = (time.monotonic(), snap)
                        fresh[ticker] = snap
                    except Exception as exc:
                        log.debug("live_data: %s fetch failed: %s", ticker, exc)
                        fresh[ticker] = None

        return fresh

    # ── Internal fetch ────────────────────────────────────────────────────────

    def _fetch(self, ticker: str) -> dict | None:
        snap = self._fetch_yfinance(ticker)
        if snap:
            return snap
        snap = self._fetch_finnhub(ticker)
        return snap

    def _fetch_yfinance(self, ticker: str) -> dict | None:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.fast_info
            # fast_info attributes vary; fall back gracefully
            current_price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
            prev_close = getattr(info, "previous_close", None) or getattr(info, "regularMarketPreviousClose", None)
            market_cap = getattr(info, "market_cap", None)
            day_high = getattr(info, "day_high", None)
            day_low = getattr(info, "day_low", None)
            volume = getattr(info, "last_volume", None) or getattr(info, "regularMarketVolume", None)
            week52_high = getattr(info, "year_high", None) or getattr(info, "fiftyTwoWeekHigh", None)
            week52_low = getattr(info, "year_low", None) or getattr(info, "fiftyTwoWeekLow", None)

            if current_price is None:
                return None

            day_change = (current_price - prev_close) if prev_close else None
            day_change_pct = (day_change / prev_close * 100) if prev_close and day_change is not None else None

            fifty_two_week_pos = None
            if week52_high and week52_low and week52_high > week52_low:
                fifty_two_week_pos = (current_price - week52_low) / (week52_high - week52_low)

            # Slow info (ratios) — optional, don't fail if unavailable
            pe_ratio = ps_ratio = div_yield = beta = short_pct = insider_pct = avg_volume = None
            try:
                slow = t.info
                pe_ratio = slow.get("trailingPE") or slow.get("forwardPE")
                ps_ratio = slow.get("priceToSalesTrailing12Months")
                div_yield = slow.get("dividendYield")
                beta = slow.get("beta")
                short_pct = slow.get("shortPercentOfFloat")
                insider_pct = slow.get("heldPercentInsiders")
                avg_volume = slow.get("averageVolume") or slow.get("averageVolume10days")
            except Exception:
                pass

            return {
                "ticker": ticker,
                "current_price": float(current_price),
                "previous_close": float(prev_close) if prev_close else None,
                "day_change": float(day_change) if day_change is not None else None,
                "day_change_pct": round(float(day_change_pct), 2) if day_change_pct is not None else None,
                "day_volume": int(volume) if volume else None,
                "average_volume": int(avg_volume) if avg_volume else None,
                "market_cap": float(market_cap) if market_cap else None,
                "fifty_two_week_high": float(week52_high) if week52_high else None,
                "fifty_two_week_low": float(week52_low) if week52_low else None,
                "fifty_two_week_position": round(float(fifty_two_week_pos), 3) if fifty_two_week_pos is not None else None,
                "pe_ratio": round(float(pe_ratio), 2) if pe_ratio else None,
                "ps_ratio": round(float(ps_ratio), 2) if ps_ratio else None,
                "dividend_yield": round(float(div_yield) * 100, 2) if div_yield else None,
                "beta": round(float(beta), 2) if beta else None,
                "short_interest_pct": round(float(short_pct) * 100, 2) if short_pct else None,
                "insider_ownership_pct": round(float(insider_pct) * 100, 2) if insider_pct else None,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "yfinance",
                "stale": False,
            }
        except Exception as exc:
            log.debug("yfinance fetch failed for %s: %s", ticker, exc)
            return None

    def _fetch_finnhub(self, ticker: str) -> dict | None:
        try:
            key = os.environ.get("FINNHUB_API_KEY", "")
            if not key:
                return None
            import httpx
            r = httpx.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": key},
                timeout=8.0,
            )
            if r.status_code != 200:
                return None
            d = r.json()
            current_price = d.get("c")
            prev_close = d.get("pc")
            if not current_price:
                return None
            day_change = current_price - prev_close if prev_close else None
            day_change_pct = (day_change / prev_close * 100) if prev_close and day_change is not None else None
            return {
                "ticker": ticker,
                "current_price": float(current_price),
                "previous_close": float(prev_close) if prev_close else None,
                "day_change": float(day_change) if day_change is not None else None,
                "day_change_pct": round(float(day_change_pct), 2) if day_change_pct is not None else None,
                "day_volume": None,
                "average_volume": None,
                "market_cap": None,
                "fifty_two_week_high": d.get("h"),
                "fifty_two_week_low": d.get("l"),
                "fifty_two_week_position": None,
                "pe_ratio": None,
                "ps_ratio": None,
                "dividend_yield": None,
                "beta": None,
                "short_interest_pct": None,
                "insider_ownership_pct": None,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "finnhub",
                "stale": False,
            }
        except Exception as exc:
            log.debug("finnhub fetch failed for %s: %s", ticker, exc)
            return None


live_price_service = LivePriceService()
