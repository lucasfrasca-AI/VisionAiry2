"""All VisionAiry2 dashboard routes."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from src.dashboard.app import app, templates
from src.dashboard import data as _data

_ROOT = Path(__file__).parent.parent.parent


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _nav_counts() -> dict:
    established = _data.list_reports("established")
    emerging = _data.list_reports("emerging_pre_ipo")
    return {
        "nav_established_count": len(established),
        "nav_emerging_count": len(emerging),
        "now_utc": _now_utc(),
    }


def _404(request: Request, nav: dict | None = None):
    return templates.TemplateResponse(
        request, "404.html", context=nav or _nav_counts(), status_code=404
    )


# ── Home ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    all_reports = _data.list_reports()
    established_count = sum(1 for r in all_reports if r["track"] == "established")
    emerging_count = sum(1 for r in all_reports if r["track"] == "emerging_pre_ipo")

    briefs = _data.list_briefs()
    latest_brief = None
    if briefs:
        b = briefs[0]
        latest_brief = {"date": b["date"], "preview_html": _data.markdown_to_html(b["markdown_preview"])}

    cost_30d = _data.get_recent_costs(30)
    sources = _data.list_sources()
    working_statuses = {"WORKING", "configured", "no-key"}
    working = sum(1 for s in sources if s["status"] in working_statuses)

    established_tickers = [r["identifier"] for r in all_reports if r["track"] == "established"][:10]
    cost_sparkline = _data.generate_cost_sparkline_svg(cost_30d)

    return templates.TemplateResponse(request, "home.html", context={
        "active_page": "home",
        "latest_reports": all_reports[:10],
        "latest_brief": latest_brief,
        "cost_30d": cost_30d,
        "cost_sparkline": cost_sparkline,
        "source_health": {"working": working, "broken": len(sources) - working, "total": len(sources)},
        "track_counts": {"established": established_count, "emerging_pre_ipo": emerging_count},
        "established_tickers": established_tickers,
        **_nav_counts(),
    })


# ── Reports list ──────────────────────────────────────────────────────────────

@app.get("/reports", response_class=HTMLResponse)
async def reports_list(request: Request, track: str = "", sector: str = "", rec: str = "", page: int = 1):
    per_page = 50
    all_reports = _data.list_reports()
    filtered = all_reports
    if track in ("established", "emerging_pre_ipo"):
        filtered = [r for r in filtered if r["track"] == track]
    if sector:
        filtered = [r for r in filtered if r.get("sector_id", "") == sector]
    if rec:
        filtered = [r for r in filtered if (r.get("recommendation") or "").upper() == rec.upper()]

    total = len(filtered)
    start = (page - 1) * per_page
    paginated = filtered[start:start + per_page]
    total_pages = max(1, (total + per_page - 1) // per_page)
    sectors = sorted({r.get("sector_id", "") for r in all_reports if r.get("sector_id")})

    return templates.TemplateResponse(request, "reports_list.html", context={
        "active_page": "reports",
        "reports": paginated,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "filter_track": track,
        "filter_sector": sector,
        "filter_rec": rec,
        "sectors": sectors,
        "recs": ["CORE", "STARTER", "WATCHLIST", "AVOID", "INSUFFICIENT_DATA"],
        **_nav_counts(),
    })


# ── Emerging list ─────────────────────────────────────────────────────────────

@app.get("/reports/emerging", response_class=HTMLResponse)
async def emerging_list(request: Request):
    reports = _data.list_reports("emerging_pre_ipo")
    return templates.TemplateResponse(request, "emerging_list.html", context={
        "active_page": "emerging",
        "reports": reports,
        **_nav_counts(),
    })


# ── Established report detail ─────────────────────────────────────────────────

@app.get("/reports/{ticker}/{timestamp}", response_class=HTMLResponse)
async def report_detail(request: Request, ticker: str, timestamp: str):
    if not _data.validate_identifier(ticker, "established"):
        return _404(request)
    if not _data.validate_timestamp(timestamp):
        return _404(request)
    report = _data.get_report(ticker, timestamp, track="established")
    if report is None:
        return _404(request)
    return templates.TemplateResponse(request, "report_view.html", context={
        "active_page": "reports",
        "report": report,
        **_nav_counts(),
    })


# ── Pre-IPO report detail ─────────────────────────────────────────────────────

@app.get("/reports/emerging/{slug}/{timestamp}", response_class=HTMLResponse)
async def emerging_report_detail(request: Request, slug: str, timestamp: str):
    if not _data.validate_identifier(slug, "emerging_pre_ipo"):
        return _404(request)
    if not _data.validate_timestamp(timestamp):
        return _404(request)
    report = _data.get_report(slug, timestamp, track="emerging_pre_ipo")
    if report is None:
        return _404(request)
    return templates.TemplateResponse(request, "report_view.html", context={
        "active_page": "emerging",
        "report": report,
        **_nav_counts(),
    })


# ── Digest ────────────────────────────────────────────────────────────────────

@app.get("/digest", response_class=HTMLResponse)
async def digest_list(request: Request):
    briefs = _data.list_briefs()
    return templates.TemplateResponse(request, "digest_list.html", context={
        "active_page": "digest",
        "briefs": briefs,
        **_nav_counts(),
    })


@app.get("/digest/{date}", response_class=HTMLResponse)
async def digest_view(request: Request, date: str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return _404(request)
    brief = _data.get_brief(date)
    if brief is None:
        return _404(request)
    tickers = list(dict.fromkeys(re.findall(r'\b([A-Z]{1,5})\b', brief["markdown"])))
    return templates.TemplateResponse(request, "digest_view.html", context={
        "active_page": "digest",
        "brief": brief,
        "referenced_tickers": tickers[:20],
        **_nav_counts(),
    })


# ── Sources ───────────────────────────────────────────────────────────────────

@app.get("/sources", response_class=HTMLResponse)
async def sources_view(request: Request):
    sources = _data.list_sources()
    working_statuses = {"WORKING", "configured", "no-key"}
    working = sum(1 for s in sources if s["status"] in working_statuses)
    return templates.TemplateResponse(request, "sources_view.html", context={
        "active_page": "sources",
        "sources": sources,
        "working_count": working,
        "total_count": len(sources),
        **_nav_counts(),
    })


# ── Live price API ────────────────────────────────────────────────────────────

@app.get("/api/price/{ticker}")
async def api_price(request: Request, ticker: str):
    if not _data.validate_identifier(ticker, "established"):
        return JSONResponse({"error": "invalid ticker"}, status_code=404)
    from src.dashboard.live_data import live_price_service
    snap = live_price_service.get_snapshot(ticker)
    if snap is None:
        return JSONResponse({"error": "no data"}, status_code=404)
    return JSONResponse(snap)


class _BulkRequest(BaseModel):
    tickers: list[str]


@app.post("/api/prices")
async def api_prices_bulk(body: _BulkRequest):
    tickers = [t for t in body.tickers if _data.validate_identifier(t, "established")][:100]
    if not tickers:
        return JSONResponse({})
    from src.dashboard.live_data import live_price_service
    results = live_price_service.get_snapshots_bulk(tickers)
    return JSONResponse({k: v for k, v in results.items()})


# ── Watchlist ─────────────────────────────────────────────────────────────────

@app.get("/watchlist", response_class=HTMLResponse)
async def watchlist_view(request: Request):
    companies = _data.list_watchlist()
    sectors: dict[str, list] = {}
    for c in companies:
        s = c["sector_id"] or "other"
        sectors.setdefault(s, []).append(c)
    return templates.TemplateResponse(request, "watchlist_view.html", context={
        "active_page": "watchlist",
        "sectors": sectors,
        "total_count": len(companies),
        **_nav_counts(),
    })
