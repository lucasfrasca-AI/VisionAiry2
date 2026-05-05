"""Read-only data accessors for the VisionAiry2 dashboard."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import markdown as _md

_ROOT = Path(__file__).parent.parent.parent
_REPORTS_ROOT = _ROOT / "reports"
_PRE_IPO_ROOT = _REPORTS_ROOT / "_emerging_pre_ipo_"
_DIGEST_ROOT = _ROOT / "digest"
_KEY_STATUS_PATH = _ROOT / "data" / ".key_status.json"

_REAL_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]+)?$")
_SLUG_RE = re.compile(r"^[a-z0-9-]{1,60}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_RE = re.compile(r"^\d{8}T\d{6}Z$")


# ── Validation ────────────────────────────────────────────────────────────────

def validate_identifier(identifier: str, track: str) -> bool:
    if track == "established":
        return bool(_REAL_TICKER_RE.match(identifier))
    if track == "emerging_pre_ipo":
        return bool(_SLUG_RE.match(identifier))
    return False


def validate_timestamp(ts: str) -> bool:
    return bool(_TS_RE.match(ts))


# ── Utilities ─────────────────────────────────────────────────────────────────

def slugify_to_display_name(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split())


def _wrap_tables(html: str) -> str:
    """Wrap each <table> in a horizontally-scrollable container."""
    import re
    return re.sub(
        r'(<table[^>]*>.*?</table>)',
        r'<div class="table-scroll-wrap">\1</div>',
        html,
        flags=re.DOTALL,
    )


def markdown_to_html(md: str) -> str:
    html = _md.markdown(md, extensions=["tables", "fenced_code"])
    return _wrap_tables(html)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _dir_size(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def _extract_frontmatter_field(report_md: str, field: str) -> str | None:
    for line in report_md.splitlines()[:10]:
        if field.lower() in line.lower():
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip().split("|")[0].strip().strip("*").strip()
    return None


def _parse_recommendation(report_md: str) -> tuple[str | None, str | None]:
    for line in report_md.splitlines()[:10]:
        low = line.lower()
        if "recommendation" in low and "|" in line:
            # Strip markdown bold markers before splitting (but keep underscores in values)
            clean = line.replace("*", "")
            parts = [p.strip() for p in clean.split("|")]
            rec = None
            conviction = None
            for p in parts:
                upper = p.upper()
                for keyword in ("AVOID", "WATCHLIST", "STARTER", "CORE", "INSUFFICIENT_DATA"):
                    if keyword in upper:
                        rec = keyword
                        break
                if "conviction" in p.lower() and ":" in p:
                    conviction = p.split(":", 1)[1].strip()
            return rec, conviction
    return None, None


def _ts_to_display(ts: str) -> str:
    try:
        dt = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ts


# ── Core list/get functions ───────────────────────────────────────────────────

def list_reports(track: str | None = None) -> list[dict]:
    results: list[dict] = []

    if track in (None, "established"):
        if _REPORTS_ROOT.exists():
            for ticker_dir in _REPORTS_ROOT.iterdir():
                if not ticker_dir.is_dir() or ticker_dir.name.startswith("_"):
                    continue
                for ts_dir in sorted(ticker_dir.iterdir(), reverse=True):
                    if not ts_dir.is_dir():
                        continue
                    report_md_path = ts_dir / "report.md"
                    if not report_md_path.exists():
                        continue
                    md_text = report_md_path.read_text()
                    rec, conviction = _parse_recommendation(md_text)
                    cost_data = _load_json(ts_dir / "cost.json") or {}
                    sector = _extract_frontmatter_field(md_text, "sector") or ""
                    results.append({
                        "track": "established",
                        "identifier": ticker_dir.name,
                        "display_name": ticker_dir.name,
                        "timestamp": ts_dir.name,
                        "timestamp_display": _ts_to_display(ts_dir.name),
                        "report_path": str(report_md_path),
                        "report_html_path": str(ts_dir / "report.html") if (ts_dir / "report.html").exists() else None,
                        "data_json_path": str(ts_dir / "data.json"),
                        "recommendation": rec,
                        "conviction": conviction,
                        "cost_usd": cost_data.get("total_usd"),
                        "sector_id": sector,
                        "size_bytes": _dir_size(ts_dir),
                        "thesis": _extract_thesis(md_text),
                        "persona_pills": _extract_personas_from_md(md_text),
                        "risks": _extract_top_risks(md_text),
                    })

    if track in (None, "emerging_pre_ipo"):
        if _PRE_IPO_ROOT.exists():
            for slug_dir in _PRE_IPO_ROOT.iterdir():
                if not slug_dir.is_dir():
                    continue
                for ts_dir in sorted(slug_dir.iterdir(), reverse=True):
                    if not ts_dir.is_dir():
                        continue
                    report_md_path = ts_dir / "report.md"
                    if not report_md_path.exists():
                        continue
                    md_text = report_md_path.read_text()
                    rec, conviction = _parse_recommendation(md_text)
                    cost_data = _load_json(ts_dir / "cost.json") or {}
                    sector = _extract_frontmatter_field(md_text, "sector") or ""
                    results.append({
                        "track": "emerging_pre_ipo",
                        "identifier": slug_dir.name,
                        "display_name": slugify_to_display_name(slug_dir.name),
                        "timestamp": ts_dir.name,
                        "timestamp_display": _ts_to_display(ts_dir.name),
                        "report_path": str(report_md_path),
                        "report_html_path": str(ts_dir / "report.html") if (ts_dir / "report.html").exists() else None,
                        "data_json_path": str(ts_dir / "data.json"),
                        "recommendation": rec,
                        "conviction": conviction,
                        "cost_usd": cost_data.get("total_usd"),
                        "sector_id": sector,
                        "size_bytes": _dir_size(ts_dir),
                        "thesis": _extract_why_surfaced(md_text) or _extract_thesis(md_text),
                        "persona_pills": _extract_personas_from_md(md_text),
                    })

    results.sort(key=lambda r: r["timestamp"], reverse=True)
    return results


def get_report(identifier: str, timestamp: str, track: str = "auto") -> dict | None:
    if track == "auto":
        if _REAL_TICKER_RE.match(identifier):
            track = "established"
        else:
            track = "emerging_pre_ipo"

    if track == "established":
        ts_dir = _REPORTS_ROOT / identifier / timestamp
    else:
        ts_dir = _PRE_IPO_ROOT / identifier / timestamp

    if not ts_dir.exists():
        return None

    report_md_path = ts_dir / "report.md"
    if not report_md_path.exists():
        return None

    md_text = report_md_path.read_text()

    # HTML — use pre-rendered if available, else generate
    html_path = ts_dir / "report.html"
    if html_path.exists():
        html_content = html_path.read_text()
    else:
        html_content = markdown_to_html(md_text)

    data = _load_json(ts_dir / "data.json") or {}
    sources = _load_json(ts_dir / "sources.json") or []
    cost = _load_json(ts_dir / "cost.json") or {}

    reasoning: dict[str, str] = {}
    reasoning_dir = ts_dir / "reasoning"
    if reasoning_dir.exists():
        for f in sorted(reasoning_dir.glob("*.md")):
            reasoning[f.stem] = f.read_text()

    rec, conviction = _parse_recommendation(md_text)
    sector = _extract_frontmatter_field(md_text, "sector") or ""

    price_history = None
    if track == "established":
        price_history = data.get("price_history") or data.get("price", {}).get("price_history")

    persona_verdicts = _extract_persona_verdicts(reasoning)

    emerging_signals: list[dict] | None = None
    if track == "emerging_pre_ipo":
        emerging_signals = _extract_emerging_signals(data)

    quant_data: dict | None = None
    if track == "established":
        quant_data = _extract_quant_data(data)

    display_name = identifier if track == "established" else slugify_to_display_name(identifier)

    return {
        "track": track,
        "identifier": identifier,
        "display_name": display_name,
        "timestamp": timestamp,
        "timestamp_display": _ts_to_display(timestamp),
        "markdown": md_text,
        "html": html_content,
        "data": data,
        "sources": sources,
        "cost": cost,
        "reasoning": reasoning,
        "persona_verdicts": persona_verdicts,
        "price_history": price_history,
        "emerging_signals": emerging_signals,
        "quant_data": quant_data,
        "recommendation": rec,
        "conviction": conviction,
        "sector_id": sector,
    }


def _safe_float(v) -> float | None:
    try:
        return float(v) if v is not None and v != "None" and v != "" else None
    except (ValueError, TypeError):
        return None


def _extract_quant_data(data: dict) -> dict | None:
    """Pull display-ready quantitative metrics from data.json fundamentals."""
    f = data.get("fundamentals") or {}
    if not isinstance(f, dict):
        return None

    week52_high = _safe_float(f.get("52WeekHigh"))
    week52_low = _safe_float(f.get("52WeekLow"))
    week52_pos: float | None = None
    if week52_high and week52_low and week52_high > week52_low:
        # Position will be updated by JS using live price; store range for bar
        week52_pos = None  # JS fills this after fetching live price

    market_cap_raw = _safe_float(f.get("MarketCapitalization"))
    market_cap_display = None
    if market_cap_raw:
        if market_cap_raw >= 1e12:
            market_cap_display = f"${market_cap_raw / 1e12:.2f}T"
        elif market_cap_raw >= 1e9:
            market_cap_display = f"${market_cap_raw / 1e9:.2f}B"
        elif market_cap_raw >= 1e6:
            market_cap_display = f"${market_cap_raw / 1e6:.2f}M"
        else:
            market_cap_display = f"${market_cap_raw:,.0f}"

    return {
        "sector": f.get("Sector") or "",
        "industry": f.get("Industry") or "",
        "market_cap_raw": market_cap_raw,
        "market_cap_display": market_cap_display,
        "pe_ratio": _safe_float(f.get("PERatio")),
        "ps_ratio": _safe_float(f.get("PriceToSalesRatioTTM")),
        "ev_ebitda": _safe_float(f.get("EVToEBITDA")),
        "beta": _safe_float(f.get("Beta")),
        "dividend_yield": _safe_float(f.get("DividendYield")),
        "week52_high": week52_high,
        "week52_low": week52_low,
        "analyst_target": _safe_float(f.get("AnalystTargetPrice")),
        "eps": _safe_float(f.get("EPS")),
        "roe": _safe_float(f.get("ReturnOnEquityTTM")),
    }


_PERSONA_ABBREVS: dict[str, str] = {
    "wood": "W", "cathie": "W",
    "druckenmiller": "D", "stan": "D",
    "burry": "B", "michael": "B",
    "lynch": "L", "peter": "L",
}


def _extract_thesis(md_text: str) -> str | None:
    """Return first meaningful sentence from the Executive Summary section (≤160 chars)."""
    in_section = False
    for line in md_text.splitlines():
        if re.match(r"^## \d*\.?\s*Executive Summary", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            if line.startswith("#"):
                break
            stripped = line.strip()
            if stripped and not stripped.startswith(">") and not stripped.startswith("**Generated") and len(stripped) > 20:
                first = re.split(r"\.\s+", stripped)[0].rstrip(".").strip()
                if len(first) > 20:
                    return (first[:157] + "…") if len(first) > 157 else first
    return None


def _extract_why_surfaced(md_text: str) -> str | None:
    """Extract first sentence from 'Why It Surfaced' section for pre-IPO cards."""
    in_section = False
    for line in md_text.splitlines():
        if re.match(r"^## \d*\.?\s*Why It Surfaced", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            if line.startswith("#"):
                break
            stripped = line.strip()
            if stripped and not stripped.startswith(">") and len(stripped) > 15:
                first = re.split(r"\.\s+", stripped)[0].rstrip(".").strip()
                return (first[:157] + "…") if len(first) > 157 else first
    return None


def _extract_personas_from_md(md_text: str) -> dict[str, str]:
    """Parse persona verdicts from '### PersonaName — VERDICT' headers in the debate section."""
    verdicts: dict[str, str] = {}
    for match in re.finditer(r"^### ([\w][\w\s]*?) — ([A-Z_]+)", md_text, re.MULTILINE):
        name_raw = match.group(1).lower()
        verdict = match.group(2)
        for key, abbrev in _PERSONA_ABBREVS.items():
            if key in name_raw and abbrev not in verdicts:
                verdicts[abbrev] = verdict
                break
    return verdicts


def _extract_top_risks(md_text: str) -> list[str]:
    """Return up to 2 risks from the numbered 'Top N risks' list in the Risk section."""
    # Locate the Risk section
    risk_section_m = re.search(r"^## \d*\.?\s*Risk", md_text, re.MULTILINE | re.IGNORECASE)
    if not risk_section_m:
        return []
    next_h2 = re.search(r"^## ", md_text[risk_section_m.end():], re.MULTILINE)
    risk_block = md_text[risk_section_m.end(): risk_section_m.end() + next_h2.start()] if next_h2 else md_text[risk_section_m.end():]

    # Find numbered items (1. 2. 3.) — prefer those under "Top N risks:" subheader
    items = re.findall(r"^\d+\.\s+(.+)$", risk_block, re.MULTILINE)
    risks = []
    for item in items[:2]:
        # Strip bold markers from "**Label:** text" → "Label: text"
        clean = re.sub(r"\*\*(.+?)\*\*:?\s*", r"\1: ", item)
        clean = re.sub(r"::\s*", ": ", clean).strip().rstrip(".")
        if len(clean) > 15:
            risks.append(clean[:115])
    return risks


def _extract_persona_verdicts(reasoning: dict[str, str]) -> dict[str, str]:
    """Extract final verdict strings from persona reasoning trace files."""
    verdicts = {}
    verdict_pattern = re.compile(r'"verdict"\s*:\s*"([^"]+)"')
    for name, text in reasoning.items():
        matches = verdict_pattern.findall(text)
        # Template placeholder strings contain "|" — skip those, take last clean match
        clean = [m for m in matches if "|" not in m]
        if clean:
            verdicts[name] = clean[-1]
        elif matches:
            verdicts[name] = matches[-1].split("|")[0].strip()
    return verdicts


def _extract_emerging_signals(data: dict) -> list[dict]:
    signals = []
    for contract in (data.get("gov_contracts") or [])[:5]:
        amt = contract.get("Award Amount") or contract.get("amount") or 0
        title = contract.get("title") or contract.get("Description") or "Gov contract"
        signals.append({"type": "gov_contract", "label": f"Gov contract: {str(title)[:80]} (${amt:,.0f})" if amt else str(title)[:80]})
    for filing in (data.get("filings_recent") or [])[:3]:
        signals.append({"type": "filing", "label": f"Filing: {filing.get('title', '')[:80]}"})
    for news in (data.get("news_recent") or [])[:2]:
        signals.append({"type": "news", "label": f"News: {news.get('title', '')[:80]}"})
    return signals


# ── Briefs ────────────────────────────────────────────────────────────────────

def list_briefs() -> list[dict]:
    if not _DIGEST_ROOT.exists():
        return []
    results = []
    for f in sorted(_DIGEST_ROOT.glob("*.md"), reverse=True):
        date = f.stem
        text = f.read_text()
        results.append({
            "date": date,
            "path": str(f.relative_to(_ROOT)),
            "size_bytes": f.stat().st_size,
            "markdown_preview": text[:500],
        })
    return results


def get_brief(date: str) -> dict | None:
    path = _DIGEST_ROOT / f"{date}.md"
    if not path.exists():
        return None
    text = path.read_text()
    return {"date": date, "markdown": text, "html": markdown_to_html(text)}


def extract_referenced_tickers(brief_markdown: str) -> list[str]:
    """Extract tickers from brief markdown by matching against watchlist + known report dirs.

    Strict: only returns strings that are real, known tickers — filters out prose noise like
    AVOID, HIGH, CUDA, FDA, AI, EV, etc.
    """
    # Build known-ticker set from config watchlist
    known: set[str] = set()
    try:
        from src.config import get_config
        cfg = get_config()
        for entries in (cfg.watchlist or {}).values():
            for e in entries:
                t = e.ticker if hasattr(e, "ticker") else (e.get("ticker", "") if isinstance(e, dict) else "")
                if t:
                    known.add(t)
    except Exception:
        pass

    # Add tickers from reports/ directory (covers analyse-ticker one-off reports)
    if _REPORTS_ROOT.exists():
        for d in _REPORTS_ROOT.iterdir():
            if d.is_dir() and not d.name.startswith("_") and _REAL_TICKER_RE.match(d.name):
                known.add(d.name)

    if not known:
        return []

    # Find 2-5 char uppercase candidates in the markdown
    candidates = set(re.findall(r'\b([A-Z]{2,5})\b', brief_markdown))
    matched = sorted(candidates & known)
    return matched


# ── Sources ───────────────────────────────────────────────────────────────────

_STATUS_ORDER = {"WORKING": 0, "configured": 0, "no-key": 0,
                 "UNVERIFIED": 1, "SET BUT UNVERIFIED": 1,
                 "INVALID": 2, "NOT_SET": 3}


def list_sources() -> list[dict]:
    raw = _load_json(_KEY_STATUS_PATH)
    if not raw:
        return []

    doc_counts: dict[str, int] = {}
    try:
        from src.storage.db import session_scope
        from src.storage.models import Document
        from sqlalchemy import func
        with session_scope() as s:
            rows = s.query(Document.source, func.count(Document.id)).group_by(Document.source).all()
            doc_counts = {r[0]: r[1] for r in rows}
    except Exception:
        pass

    results = []
    for env_var, info in raw.get("statuses", {}).items():
        status = info.get("status", "UNVERIFIED")
        results.append({
            "source_id": env_var,
            "needs_key": not status.startswith("no-key") and not status.startswith("configured"),
            "key_env_var": env_var,
            "status": status,
            "last_validated": raw.get("checked_at", ""),
            "notes": info.get("notes", ""),
            "doc_count_total": doc_counts.get(env_var.lower().replace("_api_key", ""), 0),
        })

    results.sort(key=lambda r: _STATUS_ORDER.get(r["status"], 9))
    return results


# ── Watchlist ─────────────────────────────────────────────────────────────────

def _load_sector_labels() -> dict[str, str]:
    """Return {sector_id: label} from config.yaml."""
    try:
        import yaml as _yaml
        cfg_path = _ROOT / "config.yaml"
        raw = _yaml.safe_load(cfg_path.read_text())
        return {s["id"]: s.get("label", s["id"]) for s in raw.get("sectors", [])}
    except Exception:
        return {}


def list_watchlist() -> list[dict]:
    try:
        from src.storage.db import session_scope
        from src.storage.models import Company, Report
        from sqlalchemy import func

        sector_labels = _load_sector_labels()

        with session_scope() as s:
            companies = s.query(Company).filter(Company.is_watchlist == True).all()
            report_counts = dict(
                s.query(Report.ticker, func.count(Report.id)).group_by(Report.ticker).all()
            )
            last_reports: dict[str, Report] = {}
            for r in s.query(Report).order_by(Report.generated_at.desc()).all():
                if r.ticker not in last_reports:
                    last_reports[r.ticker] = r

            now = datetime.now(timezone.utc)
            results = []
            for c in companies:
                lr = last_reports.get(c.ticker)
                last_ts = None
                days_since = None
                last_price = None
                if lr:
                    last_ts = lr.generated_at.strftime("%Y-%m-%d")
                    # generated_at may be naive — make tz-aware for delta calc
                    ga = lr.generated_at
                    if ga.tzinfo is None:
                        ga = ga.replace(tzinfo=timezone.utc)
                    days_since = (now - ga).days
                    # Try to extract last price from the report's data.json on disk
                    last_price = _extract_price_from_report(c.ticker, lr.generated_at)

                sector_id = c.sector_id or ""
                results.append({
                    "ticker": c.ticker,
                    "name": c.name or c.ticker,
                    "sector_id": sector_id,
                    "sector_label": sector_labels.get(sector_id, sector_id),
                    "tier": c.tier or "C",
                    "last_report_timestamp": last_ts,
                    "last_recommendation": lr.conviction_level if lr else None,
                    "last_conviction": lr.conviction_level if lr else None,
                    "report_count": report_counts.get(c.ticker, 0),
                    "last_price_at_report": last_price,
                    "days_since_last_report": days_since,
                })

            results.sort(key=lambda r: (r["tier"] or "C", r["ticker"]))
            return results
    except Exception:
        return []


def _extract_price_from_report(ticker: str, generated_at) -> float | None:
    """Try to pull the price from reports/<ticker>/<ts>/data.json."""
    try:
        ts_str = generated_at.strftime("%Y%m%dT%H%M%SZ")
        data_path = _REPORTS_ROOT / ticker / ts_str / "data.json"
        if not data_path.exists():
            return None
        data = _load_json(data_path)
        if not data:
            return None
        price = (
            data.get("current_price")
            or data.get("price", {}).get("current_price")
            or data.get("fundamentals", {}).get("current_price")
        )
        return float(price) if price else None
    except Exception:
        return None


# ── Cost sparkline ────────────────────────────────────────────────────────────

def generate_cost_sparkline_svg(cost_data: dict, width: int = 200, height: int = 40) -> str:
    """Generate a simple server-side SVG sparkline from daily cost data."""
    by_day = cost_data.get("by_day", [])
    if len(by_day) < 2:
        return ""
    values = [d["usd"] for d in by_day]
    max_v = max(values) or 1.0
    n = len(values)
    padding = 4
    w = width - 2 * padding
    h = height - 2 * padding
    step = w / (n - 1) if n > 1 else w
    points = []
    for i, v in enumerate(values):
        x = padding + i * step
        y = padding + h - (v / max_v) * h
        points.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(points)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" class="text-indigo-500">'
        f'<polyline points="{polyline}" fill="none" stroke="currentColor" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


# ── Cost summary ──────────────────────────────────────────────────────────────

def get_recent_costs(n_days: int = 30) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=n_days)
    total = 0.0
    by_day: dict[str, float] = {}
    by_agent: dict[str, float] = {}
    by_track: dict[str, float] = {"established": 0.0, "emerging_pre_ipo": 0.0}

    def _process_cost(ts_dir: Path, track: str) -> None:
        nonlocal total
        cost = _load_json(ts_dir / "cost.json")
        if not cost:
            return
        try:
            dt = datetime.strptime(ts_dir.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            return
        if dt < cutoff:
            return
        t = cost.get("total_usd", 0.0) or 0.0
        total += t
        day = dt.strftime("%Y-%m-%d")
        by_day[day] = by_day.get(day, 0.0) + t
        by_track[track] = by_track.get(track, 0.0) + t
        for agent, v in (cost.get("per_agent") or {}).items():
            by_agent[agent] = by_agent.get(agent, 0.0) + (v or 0.0)

    if _REPORTS_ROOT.exists():
        for td in _REPORTS_ROOT.iterdir():
            if td.is_dir() and not td.name.startswith("_"):
                for ts_dir in td.iterdir():
                    if ts_dir.is_dir():
                        _process_cost(ts_dir, "established")

    if _PRE_IPO_ROOT.exists():
        for sd in _PRE_IPO_ROOT.iterdir():
            if sd.is_dir():
                for ts_dir in sd.iterdir():
                    if ts_dir.is_dir():
                        _process_cost(ts_dir, "emerging_pre_ipo")

    day_list = [{"date": d, "usd": round(v, 4)} for d, v in sorted(by_day.items())]
    return {
        "total_usd": round(total, 4),
        "by_day": day_list,
        "by_agent": {k: round(v, 4) for k, v in by_agent.items()},
        "by_track": {k: round(v, 4) for k, v in by_track.items()},
    }
