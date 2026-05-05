"""Mode 1: Autonomous discovery scan."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("visionairy2.discover")


def run_discovery(
    sectors: Optional[list[str]] = None,
    lookback_days_quant: int = 7,
    lookback_days_qual: int = 14,
    top_n: int = 7,
    dry_run: bool = False,
    db_session_factory: Any = None,
    llm_client: Any = None,
    progress_cb=None,
) -> dict[str, Any]:
    t_start = time.time()

    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)
        else:
            log.info(msg)

    from src.config import get_config
    cfg = get_config()

    if not sectors:
        sectors = [s.id for s in cfg.sectors]

    _emit(f"[discover] Starting scan — sectors={sectors}, top_n={top_n}, dry_run={dry_run}")

    from src.agents.context import AgentContextBuilder
    from src.ingestion.scorer import InterestingnessScorer

    builder = AgentContextBuilder(db_session_factory=db_session_factory)
    scan_ctx = builder.build_for_discovery_scan(sectors, lookback_days=max(lookback_days_quant, lookback_days_qual))

    _emit(f"[discover] Fetched {len(scan_ctx['all_documents'])} deduplicated documents")

    mentions = scan_ctx.get("company_mentions", {})
    _emit(f"[discover] Resolved {len(mentions)} unique tickers from entity extraction")

    # Score each ticker
    scorer = InterestingnessScorer()
    scored: list[tuple[str, float]] = []
    all_docs_rebuilt = _rebuild_docs(scan_ctx["all_documents"])

    # Stage A: hard sector gate — filter before scoring
    doc_id_index: dict[str, Any] = {d.source_id: d for d in all_docs_rebuilt}
    filter_candidates = [
        {"ticker": t, "docs": [doc_id_index[did] for did in doc_ids if did in doc_id_index]}
        for t, doc_ids in mentions.items()
    ]
    sector_adjacency = getattr(cfg, "sector_adjacency", {})
    filtered_candidates = scorer.filter_to_sector(filter_candidates, sectors, sector_adjacency, cfg)
    n_active = sum(1 for c in filtered_candidates if c.get("sector_status") == "active")
    n_adjacent = sum(1 for c in filtered_candidates if c.get("sector_status") == "adjacent")
    n_dropped = len(filter_candidates) - len(filtered_candidates)
    _emit(f"[discover] Sector filter: {n_active} active, {n_adjacent} adjacent, {n_dropped} dropped (off-sector)")

    if not filtered_candidates:
        _emit(
            f"[discover] WARNING: No in-sector candidates found for sectors={sectors}. "
            "Either broaden to adjacent sectors or revisit source coverage."
        )
        scan_id_empty = f"scan_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        brief_path_empty = _generate_brief([], sectors, scan_ctx, db_session_factory, llm_client)
        return {
            "scan_id": scan_id_empty,
            "dry_run": dry_run,
            "n_candidates": 0,
            "top_n_tickers": [],
            "candidate_reports": [],
            "total_cost_usd": 0.0,
            "brief_path": brief_path_empty,
            "elapsed_sec": round(time.time() - t_start, 1),
        }

    allowed_tickers = {c["ticker"] for c in filtered_candidates}

    for ticker, doc_ids in mentions.items():
        if ticker not in allowed_tickers:
            continue
        sector_id = _guess_sector(ticker, sectors, cfg)
        try:
            relevant_docs = [
                (d, 1.0) for d in all_docs_rebuilt
                if d.source_id in doc_ids
            ]
            if relevant_docs:
                result_dict = scorer.score_company(ticker, relevant_docs, cfg)
                score = result_dict.get("score", 0.0)
            else:
                score = 0.0
        except Exception as exc:
            log.warning("Scoring failed for %s: %s", ticker, exc)
            score = 0.0
        scored.append((ticker, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    top_candidates = [t for t, _ in scored[:top_n]]

    _emit(f"[discover] Top {top_n} candidates: {top_candidates}")

    scan_id = f"scan_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    total_cost = 0.0

    if dry_run:
        return {
            "scan_id": scan_id,
            "dry_run": True,
            "n_candidates": len(top_candidates),
            "top_n_tickers": top_candidates,
            "scored_list": scored[:top_n],
            "total_cost_usd": 0.0,
            "elapsed_sec": round(time.time() - t_start, 1),
        }

    # Generate reports for each candidate
    candidate_reports = []
    from src.modes._pipeline import generate_candidate_report

    for ticker in top_candidates:
        sector_id = _guess_sector(ticker, sectors, cfg)
        _emit(f"[discover] Generating report for {ticker} (sector: {sector_id})")
        try:
            result = generate_candidate_report(
                ticker=ticker,
                sector_id=sector_id,
                depth="medium",
                db_session_factory=db_session_factory,
                llm_client=llm_client,
            )
            total_cost += result.get("cost_usd", 0.0)
            candidate_reports.append({
                "ticker": ticker,
                "recommendation": result.get("recommendation"),
                "conviction": result.get("conviction"),
                "report_path": result.get("report_path"),
                "cost_usd": result.get("cost_usd"),
                "aborted": result.get("aborted", False),
            })
            _emit(f"[discover] {ticker} done — {result.get('recommendation')} (${result.get('cost_usd', 0):.3f})")
        except Exception as exc:
            log.error("Report generation failed for %s: %s", ticker, exc)
            candidate_reports.append({"ticker": ticker, "error": str(exc)})

    # Generate daily brief
    brief_path = _generate_brief(candidate_reports, sectors, scan_ctx, db_session_factory, llm_client)
    _emit(f"[discover] Brief written to {brief_path}")

    # Persist scan record
    _save_scan_to_db(scan_id, sectors, lookback_days_quant, lookback_days_qual,
                     len(mentions), len(candidate_reports), total_cost, brief_path, db_session_factory)

    elapsed = round(time.time() - t_start, 1)
    _emit(f"[discover] Scan complete in {elapsed}s, total cost ${total_cost:.3f}")

    return {
        "scan_id": scan_id,
        "dry_run": False,
        "n_candidates": len(mentions),
        "top_n_tickers": top_candidates,
        "candidate_reports": candidate_reports,
        "total_cost_usd": round(total_cost, 4),
        "brief_path": brief_path,
        "elapsed_sec": elapsed,
    }


def _generate_brief(candidate_reports, sectors, scan_ctx, db_session_factory, llm_client) -> str:
    from src.agents.synthesis.daily_brief import DailyBriefWriterAgent
    from src.agents.base import AgentInput
    from datetime import date

    today = date.today().isoformat()
    brief_dir = Path("digest")
    brief_dir.mkdir(exist_ok=True)
    brief_path = brief_dir / f"{today}.md"

    readable_reports = []
    for cr in candidate_reports:
        entry: dict = {"ticker": cr.get("ticker"), "recommendation": cr.get("recommendation"),
                       "conviction": cr.get("conviction")}
        rp = cr.get("report_path")
        if rp and Path(rp).exists():
            content = Path(rp).read_text()[:2000]
            entry["report_excerpt"] = content
        readable_reports.append(entry)

    source_failures = [k for k, v in scan_ctx.get("all_documents", [{}])[0].items()
                       if False] if scan_ctx.get("all_documents") else []

    ctx = {
        "date": today,
        "sectors_scanned": sectors,
        "candidate_reports": readable_reports,
        "watchlist_alerts": [],
        "source_failures": source_failures,
    }

    agent = DailyBriefWriterAgent(llm_client, db_session_factory)
    inp = AgentInput(target="discovery_scan", context_data=ctx, config={})
    try:
        output = agent.run(inp)
        brief_text = output.raw_response
    except Exception as exc:
        brief_text = f"# Daily Brief — {today}\n\nBrief generation failed: {exc}\n\n"
        for cr in candidate_reports:
            brief_text += f"- {cr.get('ticker')}: {cr.get('recommendation', 'N/A')}\n"

    brief_path.write_text(brief_text)
    return str(brief_path)


def _guess_sector(ticker: str, sectors: list[str], cfg: Any) -> str:
    for sector in cfg.watchlist:
        tickers_in_sector = cfg.watchlist.get(sector, [])
        for entry in tickers_in_sector:
            if isinstance(entry, dict) and entry.get("ticker") == ticker:
                return sector
    return sectors[0] if sectors else "ai_chips_compute"


def _rebuild_docs(doc_dicts: list[dict]) -> list:
    from src.sources.base import SourceDocument
    from datetime import timezone
    docs = []
    for d in doc_dicts:
        try:
            docs.append(SourceDocument(
                source=d.get("source", ""),
                source_id=d.get("source_id", ""),
                url=d.get("url", ""),
                content_hash=d.get("source_id", ""),
                doc_type=d.get("doc_type", "other"),
                title=d.get("title", ""),
                published_at=None,
                fetched_at=datetime.now(timezone.utc),
                raw_payload=d.get("raw_payload", {}),
                summary=d.get("summary"),
            ))
        except Exception:
            pass
    return docs


def _save_scan_to_db(scan_id, sectors, quant_days, qual_days, n_candidates, n_reported,
                     total_cost, brief_path, db_session_factory):
    if not db_session_factory:
        return
    try:
        from src.storage.db import session_scope
        from src.storage.models import DiscoveryScan
        from ulid import ULID
        with session_scope() as s:
            row = DiscoveryScan(
                id=str(ULID()),
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                lookback_quant_days=quant_days,
                lookback_qual_days=qual_days,
                candidates_surfaced=n_candidates,
                candidates_reported=n_reported,
                total_cost_estimate=total_cost,
                brief_path=brief_path,
            )
            s.add(row)
            s.commit()
    except Exception as exc:
        log.warning("DB scan save failed: %s", exc)
