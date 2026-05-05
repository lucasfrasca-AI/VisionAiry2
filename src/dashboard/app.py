"""VisionAiry2 FastAPI dashboard — read-only, localhost only."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

log = logging.getLogger("visionairy2.dashboard")

_ROOT = Path(__file__).parent.parent.parent  # project root

app = FastAPI(title="VisionAiry2 Dashboard", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.on_event("startup")
async def _startup() -> None:
    established = sum(
        1 for d in (_ROOT / "reports").iterdir()
        if d.is_dir() and not d.name.startswith("_")
    ) if (_ROOT / "reports").exists() else 0
    pre_ipo_root = _ROOT / "reports" / "_emerging_pre_ipo_"
    pre_ipo = sum(1 for d in pre_ipo_root.iterdir() if d.is_dir()) if pre_ipo_root.exists() else 0
    briefs = len(list((_ROOT / "digest").glob("*.md"))) if (_ROOT / "digest").exists() else 0
    log.info(
        "Dashboard started. Project root: %s | Established reports: %d | "
        "Pre-IPO reports: %d | Briefs: %d",
        _ROOT, established, pre_ipo, briefs,
    )


@app.middleware("http")
async def _access_log(request: Request, call_next):
    response = await call_next(request)
    log.info("%s %s → %d", request.method, request.url.path, response.status_code)
    return response


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Exception handlers ────────────────────────────────────────────────────────

@app.exception_handler(404)
async def _404(request: Request, exc):
    return templates.TemplateResponse(
        request, "404.html", context={"now_utc": _now_utc()}, status_code=404
    )


@app.exception_handler(500)
async def _500(request: Request, exc):
    return templates.TemplateResponse(
        request, "500.html", context={"now_utc": _now_utc()}, status_code=500
    )


# ── Import routes (registered after app is created) ──────────────────────────

from src.dashboard import routes as _routes  # noqa: E402, F401
