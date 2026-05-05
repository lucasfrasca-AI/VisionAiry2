"""All VisionAiry2 dashboard routes."""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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

    rec_counts: dict[str, int] = {}
    for r in filtered:
        k = (r.get("recommendation") or "UNKNOWN").upper()
        rec_counts[k] = rec_counts.get(k, 0) + 1

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
        "rec_counts": rec_counts,
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
    referenced_tickers = _data.extract_referenced_tickers(brief["markdown"])
    return templates.TemplateResponse(request, "digest_view.html", context={
        "active_page": "digest",
        "brief": brief,
        "referenced_tickers": referenced_tickers[:20],
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
def api_prices_bulk(body: _BulkRequest):
    tickers = [t for t in body.tickers if _data.validate_identifier(t, "established")][:100]
    if not tickers:
        return JSONResponse({})
    from src.dashboard.live_data import live_price_service
    try:
        results = live_price_service.get_snapshots_bulk(tickers)
        return JSONResponse({k: v for k, v in results.items() if v is not None})
    except Exception:
        return JSONResponse({}, status_code=200)


# ── On-demand analysis ────────────────────────────────────────────────────────

_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]+)?$")
_REPORTS_ROOT = _ROOT / "reports"


def _sector_ids() -> list[str]:
    try:
        from src.config import get_config
        cfg = get_config()
        return [s.id for s in cfg.sectors]
    except Exception:
        return []


@app.get("/analyse", response_class=HTMLResponse)
async def analyse_form(request: Request):
    return templates.TemplateResponse(request, "analyse_form.html", context={
        "active_page": "analyse",
        "sectors": _sector_ids(),
        "error": None,
        "submitted_ticker": None,
        **_nav_counts(),
    })


@app.post("/analyse", response_class=HTMLResponse)
async def analyse_submit(
    request: Request,
    ticker: str = Form(...),
    depth: str = Form("full"),
    sector: str = Form(""),
):
    ticker = ticker.upper().strip()

    if not _TICKER_RE.match(ticker):
        return templates.TemplateResponse(request, "analyse_form.html", context={
            "active_page": "analyse",
            "sectors": _sector_ids(),
            "error": f"Invalid ticker format: {ticker!r}. Must be 1–5 uppercase letters.",
            "submitted_ticker": ticker,
            **_nav_counts(),
        })
    if depth not in ("full", "lite"):
        depth = "full"

    # Resolve sector
    sector_id = sector or None
    if not sector_id:
        try:
            from src.config import get_config
            cfg = get_config()
            for wl_sector, entries in (cfg.watchlist or {}).items():
                for e in entries:
                    t = e.ticker if hasattr(e, "ticker") else (e.get("ticker", "") if isinstance(e, dict) else "")
                    if t == ticker:
                        sector_id = wl_sector
                        break
                if sector_id:
                    break
            if not sector_id and cfg.sectors:
                sector_id = cfg.sectors[0].id
        except Exception:
            sector_id = "ai_chips_compute"

    # Expected timestamp prefix (first 8 chars = date) — we'll check for any ts today
    now_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    today_prefix = now_ts[:8]  # e.g. "20260505"

    # Spawn background subprocess (non-blocking)
    import shutil
    log_path = Path("/tmp") / f"visionairy2_analyse_{ticker}_{now_ts}.log"
    uv_path = shutil.which("uv")
    try:
        with open(log_path, "w") as log_file:
            if uv_path:
                cmd = [uv_path, "run", "visionairy2", "analyse-ticker", ticker,
                       "--depth", depth, "--sector", sector_id]
            else:
                root_str = str(_ROOT)
                cmd = [
                    sys.executable, "-c",
                    f"import sys; sys.path.insert(0,{root_str!r}); from src.cli import app; "
                    f"sys.argv=['visionairy2','analyse-ticker',{ticker!r},'--depth',{depth!r},'--sector',{sector_id!r}]; app()",
                ]
            subprocess.Popen(cmd, stdout=log_file, stderr=log_file, cwd=str(_ROOT))
    except Exception as exc:
        return templates.TemplateResponse(request, "analyse_form.html", context={
            "active_page": "analyse",
            "sectors": _sector_ids(),
            "error": f"Failed to start analysis process: {exc}",
            "submitted_ticker": ticker,
            **_nav_counts(),
        })

    return RedirectResponse(
        f"/analyse/status/{ticker}?depth={depth}&sector_id={sector_id}&started={now_ts}&today={today_prefix}",
        status_code=303,
    )


@app.get("/analyse/status/{ticker}", response_class=HTMLResponse)
async def analyse_status(
    request: Request,
    ticker: str,
    depth: str = "full",
    sector_id: str = "",
    started: str = "",
    today: str = "",
):
    if not _TICKER_RE.match(ticker):
        return _404(request)

    # Check if report exists: look for any ts_dir created today for this ticker
    ticker_dir = _REPORTS_ROOT / ticker
    found_ts: Optional[str] = None
    if ticker_dir.exists():
        # Most recent ts_dir for this ticker that starts with today's date prefix
        for ts_dir in sorted(ticker_dir.iterdir(), reverse=True):
            if not ts_dir.is_dir():
                continue
            ts_name = ts_dir.name
            if today and not ts_name.startswith(today):
                continue
            report_md = ts_dir / "report.md"
            data_json = ts_dir / "data.json"
            if report_md.exists() and data_json.exists():
                found_ts = ts_name
                break

    started_display = ""
    if started:
        try:
            dt = datetime.strptime(started, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            started_display = dt.strftime("%H:%M:%S UTC")
        except Exception:
            started_display = started

    return templates.TemplateResponse(request, "analyse_status.html", context={
        "active_page": "analyse",
        "ticker": ticker,
        "depth": depth,
        "sector_id": sector_id or "auto",
        "started_at": started_display,
        "expected_ts": today + "T*",
        "done": found_ts is not None,
        "timestamp": found_ts or "",
        "error": None,
        **_nav_counts(),
    })


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
