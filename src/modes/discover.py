"""Mode 1: Autonomous discovery scan — established + emerging two-track."""
from __future__ import annotations

import logging
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("visionairy2.discover")

_REAL_TICKER_RE = re.compile(r'^[A-Z]{1,5}(\.[A-Z]+)?$')


def slugify_entity_name(name: str) -> str:
    """Convert entity name to filesystem-safe slug."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9-]+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:60]


def _is_real_ticker(s: str) -> bool:
    return bool(_REAL_TICKER_RE.match(s))


def run_discovery(
    sectors: Optional[list[str]] = None,
    lookback_days_quant: int = 7,
    lookback_days_qual: int = 14,
    top_n: int = 7,
    dry_run: bool = False,
    db_session_factory: Any = None,
    llm_client: Any = None,
    progress_cb=None,
    established_n: Optional[int] = None,
    emerging_n: Optional[int] = None,
    emerging_only: bool = False,
    established_only: bool = False,
) -> dict[str, Any]:
    import sys
    t_start = time.time()

    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)
        else:
            log.info(msg)

    def _phase(msg: str):
        """Print a phase-boundary line to stdout with timestamp, flushing immediately."""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        log.info(msg)

    from src.config import get_config
    cfg = get_config()

    if not sectors:
        sectors = [s.id for s in cfg.sectors]

    # Compute established/emerging split
    if established_only:
        n_est = top_n
        n_em = 0
    elif emerging_only:
        n_est = 0
        n_em = top_n
    else:
        n_est = established_n if established_n is not None else max(1, round(top_n * 0.6))
        n_em = emerging_n if emerging_n is not None else max(1 if top_n >= 2 else 0, top_n - n_est)

    _phase(f"Phase 1/8: Fetching from sources — sectors={sectors}, lookback={lookback_days_qual}d")
    _emit(f"[discover] Starting scan — sectors={sectors}, top_n={top_n} "
          f"(established={n_est}, emerging={n_em}), dry_run={dry_run}")

    _warn_orphaned_report_dirs(_emit)

    from src.agents.context import AgentContextBuilder
    from src.ingestion.scorer import InterestingnessScorer

    builder = AgentContextBuilder(db_session_factory=db_session_factory)
    scan_ctx = builder.build_for_discovery_scan(
        sectors, lookback_days=max(lookback_days_quant, lookback_days_qual)
    )

    n_main_docs = len(scan_ctx['all_documents'])
    _phase(f"Phase 1/8: Main sources done — {n_main_docs} documents fetched")

    # Also fetch from emerging-signal sources
    emerging_docs = _fetch_emerging_sources(sectors, cfg, lookback_days_qual, _emit)
    all_emerging_flat = [d for docs in emerging_docs.values() for d in docs]

    n_sources_ok = len([k for k, v in emerging_docs.items() if v])
    _phase(f"Phase 1/8: Done — {n_main_docs + len(all_emerging_flat)} total docs "
           f"({n_main_docs} main + {len(all_emerging_flat)} emerging, {n_sources_ok} emerging sources returned data)")

    _phase("Phase 2/8: Deduplicating documents")
    mentions = scan_ctx.get("company_mentions", {})
    _phase(f"Phase 2/8: Done — {n_main_docs} docs after dedup")

    _phase("Phase 3/8: Entity extraction (from documents)")
    _emit(f"[discover] Resolved {len(mentions)} unique tickers from entity extraction")

    # Merge emerging entities into mentions
    emerging_mentions = _extract_emerging_entities(all_emerging_flat)
    for entity, doc_ids in emerging_mentions.items():
        if entity not in mentions:
            mentions[entity] = []
        mentions[entity] = list(set(mentions.get(entity, []) + doc_ids))

    _phase(f"Phase 3/8: Done — {len(mentions)} unique entities found")

    scorer = InterestingnessScorer()
    all_docs_rebuilt = _rebuild_docs(scan_ctx["all_documents"])
    all_docs_rebuilt.extend(all_emerging_flat)

    _phase(f"Phase 4/8: Sector filter — {len(mentions)} candidates against sectors={sectors}")
    # Stage A: hard sector gate
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
    _phase(f"Phase 4/8: Done — {n_active} active, {n_adjacent} adjacent, {n_dropped} dropped (off-sector)")
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

    _phase("Phase 5/8: Scoring + track split")
    # Stage B: split into established / emerging tracks
    established_candidates, emerging_candidates = scorer.split_candidates(filtered_candidates, cfg)
    _emit(f"[discover] Track split: {len(established_candidates)} established, "
          f"{len(emerging_candidates)} emerging")

    # Score each track
    established_scores: list[dict] = []
    for c in established_candidates:
        ticker = c.get("ticker", "")
        docs = c.get("docs", [])
        try:
            doc_links = [(d, 1.0) for d in docs]
            scored = scorer.score_company(ticker, doc_links, cfg)
            scored["track"] = "established"
            established_scores.append(scored)
        except Exception as exc:
            log.warning("Established scoring failed for %s: %s", ticker, exc)

    # Populate seen slugs from pre-IPO report dirs so novelty bonus is accurate
    _pre_ipo_root = Path("reports/_emerging_pre_ipo_")
    seen_tickers: set[str] = set()
    if _pre_ipo_root.exists():
        for _slug_dir in _pre_ipo_root.iterdir():
            if _slug_dir.is_dir():
                seen_tickers.add(_slug_dir.name)

    # Collect watchlist tickers for the subsidiary filter
    _watchlist_tickers: set[str] = set()
    for _entries in (cfg.watchlist or {}).values():
        for _e in _entries:
            _t = _e.ticker if hasattr(_e, "ticker") else (_e.get("ticker", "") if isinstance(_e, dict) else "")
            if _t and len(_t) >= 3:
                _watchlist_tickers.add(_t)

    emerging_scores: list[dict] = []
    for c in emerging_candidates:
        ticker = c.get("ticker", "")
        docs = c.get("docs", [])
        try:
            doc_links = [(d, 1.0) for d in docs]
            scored = scorer.score_emerging(ticker, doc_links, cfg, seen_tickers=seen_tickers)
            scored["track"] = "emerging"
            emerging_scores.append(scored)
        except Exception as exc:
            log.warning("Emerging scoring failed for %s: %s", ticker, exc)

    # Apply pre-IPO confidence gate: name filter + subsidiary filter + threshold
    emerging_scores, _dropped_emerging = scorer.filter_emerging_pre_ipo(
        emerging_scores, _watchlist_tickers, seen_tickers, _emit
    )
    n_em_dropped = len(_dropped_emerging)

    two_track = scorer.rank_two_tracks(
        established_scores, emerging_scores, n_established=n_est, n_emerging=n_em
    )
    top_established = [r["company_id"] for r in two_track["established"]]
    top_emerging = [r["company_id"] for r in two_track["emerging"]]
    top_candidates = top_established + top_emerging

    _phase(
        f"Phase 5/8: Done — {len(top_established)} established, {len(top_emerging)} emerging selected"
        + (f", {n_em_dropped} below-threshold dropped" if n_em_dropped else "")
    )
    _emit(f"[discover] Established candidates: {top_established}")
    _emit(f"[discover] Emerging candidates:    {top_emerging}")
    _emit(f"[discover] Split stats: {two_track['split_stats']}")

    scan_id = f"scan_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    if dry_run:
        return {
            "scan_id": scan_id,
            "dry_run": True,
            "n_candidates": len(top_candidates),
            "top_n_tickers": top_candidates,
            "established": top_established,
            "emerging": top_emerging,
            "split_stats": two_track["split_stats"],
            "total_cost_usd": 0.0,
            "elapsed_sec": round(time.time() - t_start, 1),
        }

    # Generate reports for all candidates
    total_cost = 0.0
    candidate_reports = []
    from src.modes._pipeline import generate_candidate_report

    n_to_generate = len(top_established) + len(top_emerging)
    _phase(f"Phase 6/8: Generating {n_to_generate} reports — est. {2*n_to_generate}–{3*n_to_generate} min")
    _report_idx = [0]

    for ticker in top_established:
        _report_idx[0] += 1
        sector_id = _guess_sector(ticker, sectors, cfg)
        _phase(f"Phase 6/8: Report {_report_idx[0]}/{n_to_generate} — {ticker} (established, {sector_id})")
        _emit(f"[discover] Generating report for {ticker} (established, sector: {sector_id})")
        try:
            result = generate_candidate_report(
                ticker=ticker,
                sector_id=sector_id,
                depth="medium",
                db_session_factory=db_session_factory,
                llm_client=llm_client,
            )
            total_cost += result.get("cost_usd", 0.0)
            rec = result.get("recommendation")
            cost = result.get("cost_usd", 0.0)
            candidate_reports.append({
                "ticker": ticker,
                "track": "established",
                "recommendation": rec,
                "conviction": result.get("conviction"),
                "report_path": result.get("report_path"),
                "cost_usd": cost,
                "aborted": result.get("aborted", False),
            })
            _phase(f"Phase 6/8: Report {_report_idx[0]}/{n_to_generate} done — {ticker} → {rec} (${cost:.3f})")
            _emit(f"[discover] {ticker} done — {rec} (${cost:.3f})")
        except Exception as exc:
            log.error("Report generation failed for %s: %s", ticker, exc)
            _phase(f"Phase 6/8: Report {_report_idx[0]}/{n_to_generate} FAILED — {ticker}: {exc}")
            candidate_reports.append({"ticker": ticker, "track": "established", "error": str(exc)})

    for ticker in top_emerging:
        _report_idx[0] += 1
        sector_id = _guess_sector(ticker, sectors, cfg)
        _phase(f"Phase 6/8: Report {_report_idx[0]}/{n_to_generate} — {ticker} (emerging, {sector_id})")
        _emit(f"[discover] Generating report for {ticker} (emerging, sector: {sector_id})")
        # Treat as pre-IPO if no real ticker format OR explicitly flagged
        c_data = next((c for c in emerging_candidates if c.get("ticker") == ticker), {})
        is_pre_ipo = c_data.get("is_pre_ipo", False) or not _is_real_ticker(ticker)
        report_depth = "lite" if is_pre_ipo else "medium"
        try:
            result = generate_candidate_report(
                ticker=ticker,
                sector_id=sector_id,
                depth=report_depth,
                db_session_factory=db_session_factory,
                llm_client=llm_client,
                is_pre_ipo=is_pre_ipo,
            )
            total_cost += result.get("cost_usd", 0.0)
            rp = result.get("report_path", "")
            if (not _is_real_ticker(ticker) or is_pre_ipo) and rp:
                # Reroute to reports/_emerging_pre_ipo_/<slug>/<ts>/
                slug = slugify_entity_name(ticker)
                ts_report = result.get("timestamp", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
                pre_ipo_dir = Path("reports/_emerging_pre_ipo_") / slug / ts_report
                src_dir = Path(rp).parent
                if src_dir.exists() and src_dir != pre_ipo_dir:
                    pre_ipo_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src_dir), str(pre_ipo_dir))
                rp = str(pre_ipo_dir / Path(rp).name)
            rec = result.get("recommendation")
            cost = result.get("cost_usd", 0.0)
            candidate_reports.append({
                "ticker": ticker,
                "track": "emerging",
                "is_pre_ipo": is_pre_ipo,
                "recommendation": rec,
                "conviction": result.get("conviction"),
                "report_path": rp,
                "cost_usd": cost,
                "aborted": result.get("aborted", False),
            })
            _phase(f"Phase 6/8: Report {_report_idx[0]}/{n_to_generate} done — {ticker} → {rec} (${cost:.3f})")
            _emit(f"[discover] {ticker} done — {rec} (${cost:.3f})")
        except Exception as exc:
            log.error("Emerging report generation failed for %s: %s", ticker, exc)
            _phase(f"Phase 6/8: Report {_report_idx[0]}/{n_to_generate} FAILED — {ticker}: {exc}")
            candidate_reports.append({"ticker": ticker, "track": "emerging", "error": str(exc)})

    _phase("Phase 7/8: Writing daily brief")
    brief_path = _generate_brief(candidate_reports, sectors, scan_ctx, db_session_factory, llm_client)
    _phase(f"Phase 7/8: Done — brief at {brief_path}")
    _emit(f"[discover] Brief written to {brief_path}")

    _save_scan_to_db(scan_id, sectors, lookback_days_quant, lookback_days_qual,
                     len(mentions), len(candidate_reports), total_cost, brief_path, db_session_factory)

    elapsed = round(time.time() - t_start, 1)
    _phase(f"Phase 8/8: Scan complete in {elapsed}s — total cost ${total_cost:.3f}")
    _emit(f"[discover] Scan complete in {elapsed}s, total cost ${total_cost:.3f}")

    return {
        "scan_id": scan_id,
        "dry_run": False,
        "n_candidates": len(mentions),
        "top_n_tickers": top_candidates,
        "established": top_established,
        "emerging": top_emerging,
        "split_stats": two_track["split_stats"],
        "candidate_reports": candidate_reports,
        "total_cost_usd": round(total_cost, 4),
        "brief_path": brief_path,
        "elapsed_sec": elapsed,
    }


def _fetch_emerging_sources(
    sectors: list[str],
    cfg: Any,
    lookback_days: int,
    emit,
) -> dict[str, list]:
    """Fetch from all emerging-signal sources. Returns {source_id: [SourceDocument]}."""
    from src.sources.base import SourceQuery
    results: dict[str, list] = {}

    # Collect keywords for active sectors
    keywords: list[str] = []
    for s in cfg.sectors:
        if s.id in sectors:
            keywords.extend(s.keywords[:3])

    keyword_str = " ".join(keywords[:3]) if keywords else "technology"

    source_configs = [
        ("polygon_ipo", SourceQuery(limit=50, extra={})),
        ("sbir", SourceQuery(query_string=keyword_str, lookback_days=lookback_days, limit=50)),
        ("edgar_fulltext", SourceQuery(query_string=keyword_str, lookback_days=90, limit=25,
                                       extra={"forms": "S-1,S-1/A,F-1,F-1/A,DRS"})),
        ("finnhub", SourceQuery(ticker="", limit=50, extra={"endpoint": "calendar/ipo"})),
        ("nsf_awards", SourceQuery(query_string=keyword_str, lookback_days=180, limit=25)),
        ("sec_tickers_delta", SourceQuery(limit=50)),
        ("usaspending", SourceQuery(query_string=keyword_str, lookback_days=90, limit=50,
                                    extra={"endpoint": "subawards",
                                           "keywords": keywords[:3]})),
    ]

    # GitHub topic-search per sector
    github_topics_by_sector = getattr(cfg, "github_topics_by_sector", {})
    for sector_id in sectors:
        topics = github_topics_by_sector.get(sector_id, [])
        if topics:
            source_configs.append((
                "github",
                SourceQuery(limit=20, extra={"endpoint": "topic-search", "topics": topics}),
            ))

    from src.sources.registry import get_client
    for source_id, query in source_configs:
        try:
            client = get_client(source_id, cfg)
            if not client.is_available():
                continue
            result = client.fetch(query)
            if result.documents:
                results[source_id] = result.documents
                emit(f"[discover] {source_id}: {len(result.documents)} emerging docs")
            elif result.errors:
                emit(f"[discover] {source_id}: {result.errors[0][:80]}")
        except Exception as exc:
            emit(f"[discover] {source_id} fetch failed: {exc}")

    return results


def _warn_orphaned_report_dirs(emit) -> None:
    """Warn (do not delete) if top-level report dirs with spaces or special chars exist."""
    reports_root = Path("reports")
    if not reports_root.exists():
        return
    _reserved = {"_emerging_pre_ipo_", "_doc_analysis_"}
    bad = [
        d.name for d in reports_root.iterdir()
        if d.is_dir() and d.name not in _reserved and not _REAL_TICKER_RE.match(d.name)
    ]
    if bad:
        emit(
            f"[discover] WARNING: Found {len(bad)} orphaned report dir(s) with non-slug names "
            f"({bad[:3]}{'...' if len(bad) > 3 else ''}). "
            "Move to reports/_emerging_pre_ipo_/ or delete manually."
        )


def _extract_emerging_entities(docs: list) -> dict[str, list[str]]:
    """Extract entity names from emerging-source documents and build ticker-like keys."""
    entities: dict[str, list[str]] = {}
    for doc in docs:
        mentioned = getattr(doc, "entities_mentioned", [])
        for name in mentioned:
            if name and len(name) > 1:
                key = name[:40]
                if key not in entities:
                    entities[key] = []
                if doc.source_id not in entities[key]:
                    entities[key].append(doc.source_id)
    return entities


def _generate_brief(candidate_reports, sectors, scan_ctx, db_session_factory, llm_client) -> str:
    from src.agents.synthesis.daily_brief import DailyBriefWriterAgent
    from src.agents.base import AgentInput
    from datetime import date

    today = date.today().isoformat()
    brief_dir = Path("digest")
    brief_dir.mkdir(exist_ok=True)
    brief_path = brief_dir / f"{today}.md"

    established_reports = [r for r in candidate_reports if r.get("track") == "established"]
    emerging_reports = [r for r in candidate_reports if r.get("track") == "emerging"]

    readable_reports = []
    for cr in candidate_reports:
        entry: dict = {
            "ticker": cr.get("ticker"),
            "track": cr.get("track", "established"),
            "recommendation": cr.get("recommendation"),
            "conviction": cr.get("conviction"),
        }
        rp = cr.get("report_path")
        if rp and Path(rp).exists():
            content = Path(rp).read_text()[:2000]
            entry["report_excerpt"] = content
        readable_reports.append(entry)

    ctx = {
        "date": today,
        "sectors_scanned": sectors,
        "candidate_reports": readable_reports,
        "established_count": len(established_reports),
        "emerging_count": len(emerging_reports),
        "watchlist_alerts": [],
        "source_failures": [],
    }

    agent = DailyBriefWriterAgent(llm_client, db_session_factory)
    inp = AgentInput(target="discovery_scan", context_data=ctx, config={})
    try:
        output = agent.run(inp)
        brief_text = output.raw_response
    except Exception as exc:
        brief_text = f"# Daily Brief — {today}\n\nBrief generation failed: {exc}\n\n"
        for cr in candidate_reports:
            track = cr.get("track", "established")
            brief_text += f"- [{track}] {cr.get('ticker')}: {cr.get('recommendation', 'N/A')}\n"

    brief_path.write_text(brief_text)
    return str(brief_path)


def _guess_sector(ticker: str, sectors: list[str], cfg: Any) -> str:
    for sector in cfg.watchlist:
        tickers_in_sector = cfg.watchlist.get(sector, [])
        for entry in tickers_in_sector:
            if isinstance(entry, dict) and entry.get("ticker") == ticker:
                return sector
            if hasattr(entry, "ticker") and entry.ticker == ticker:
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
