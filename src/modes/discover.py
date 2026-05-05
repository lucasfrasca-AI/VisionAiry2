"""Mode 1: Autonomous discovery scan — established + emerging two-track."""
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
    established_n: Optional[int] = None,
    emerging_n: Optional[int] = None,
    emerging_only: bool = False,
    established_only: bool = False,
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

    _emit(f"[discover] Starting scan — sectors={sectors}, top_n={top_n} "
          f"(established={n_est}, emerging={n_em}), dry_run={dry_run}")

    from src.agents.context import AgentContextBuilder
    from src.ingestion.scorer import InterestingnessScorer

    builder = AgentContextBuilder(db_session_factory=db_session_factory)
    scan_ctx = builder.build_for_discovery_scan(
        sectors, lookback_days=max(lookback_days_quant, lookback_days_qual)
    )

    _emit(f"[discover] Fetched {len(scan_ctx['all_documents'])} deduplicated documents")

    # Also fetch from emerging-signal sources
    emerging_docs = _fetch_emerging_sources(sectors, cfg, lookback_days_qual, _emit)
    all_emerging_flat = [d for docs in emerging_docs.values() for d in docs]
    _emit(f"[discover] Emerging sources returned {len(all_emerging_flat)} additional documents")

    mentions = scan_ctx.get("company_mentions", {})
    _emit(f"[discover] Resolved {len(mentions)} unique tickers from entity extraction")

    # Merge emerging entities into mentions
    emerging_mentions = _extract_emerging_entities(all_emerging_flat)
    for entity, doc_ids in emerging_mentions.items():
        if entity not in mentions:
            mentions[entity] = []
        mentions[entity] = list(set(mentions.get(entity, []) + doc_ids))

    scorer = InterestingnessScorer()
    all_docs_rebuilt = _rebuild_docs(scan_ctx["all_documents"])
    all_docs_rebuilt.extend(all_emerging_flat)

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

    seen_tickers: set[str] = set()  # could be populated from DB history
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

    two_track = scorer.rank_two_tracks(
        established_scores, emerging_scores, n_established=n_est, n_emerging=n_em
    )
    top_established = [r["company_id"] for r in two_track["established"]]
    top_emerging = [r["company_id"] for r in two_track["emerging"]]
    top_candidates = top_established + top_emerging

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

    for ticker in top_established:
        sector_id = _guess_sector(ticker, sectors, cfg)
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
            candidate_reports.append({
                "ticker": ticker,
                "track": "established",
                "recommendation": result.get("recommendation"),
                "conviction": result.get("conviction"),
                "report_path": result.get("report_path"),
                "cost_usd": result.get("cost_usd"),
                "aborted": result.get("aborted", False),
            })
            _emit(f"[discover] {ticker} done — {result.get('recommendation')} (${result.get('cost_usd', 0):.3f})")
        except Exception as exc:
            log.error("Report generation failed for %s: %s", ticker, exc)
            candidate_reports.append({"ticker": ticker, "track": "established", "error": str(exc)})

    for ticker in top_emerging:
        sector_id = _guess_sector(ticker, sectors, cfg)
        _emit(f"[discover] Generating report for {ticker} (emerging, sector: {sector_id})")
        # Check if pre-IPO (no real ticker or only from pre-market sources)
        c_data = next((c for c in emerging_candidates if c.get("ticker") == ticker), {})
        is_pre_ipo = c_data.get("is_pre_ipo", False)
        report_depth = "lite" if is_pre_ipo else "medium"
        try:
            result = generate_candidate_report(
                ticker=ticker,
                sector_id=sector_id,
                depth=report_depth,
                db_session_factory=db_session_factory,
                llm_client=llm_client,
            )
            total_cost += result.get("cost_usd", 0.0)
            rp = result.get("report_path", "")
            if is_pre_ipo and rp:
                # Reroute report to _emerging_pre_ipo_ directory
                slug = ticker.lower().replace(" ", "_")[:30]
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                pre_ipo_dir = Path(f"reports/_emerging_pre_ipo_/{slug}/{ts}")
                pre_ipo_dir.mkdir(parents=True, exist_ok=True)
                src_path = Path(rp)
                if src_path.exists():
                    dest = pre_ipo_dir / src_path.name
                    dest.write_text(src_path.read_text())
                    rp = str(dest)
            candidate_reports.append({
                "ticker": ticker,
                "track": "emerging",
                "is_pre_ipo": is_pre_ipo,
                "recommendation": result.get("recommendation"),
                "conviction": result.get("conviction"),
                "report_path": rp,
                "cost_usd": result.get("cost_usd"),
                "aborted": result.get("aborted", False),
            })
            _emit(f"[discover] {ticker} done — {result.get('recommendation')} (${result.get('cost_usd', 0):.3f})")
        except Exception as exc:
            log.error("Emerging report generation failed for %s: %s", ticker, exc)
            candidate_reports.append({"ticker": ticker, "track": "emerging", "error": str(exc)})

    brief_path = _generate_brief(candidate_reports, sectors, scan_ctx, db_session_factory, llm_client)
    _emit(f"[discover] Brief written to {brief_path}")

    _save_scan_to_db(scan_id, sectors, lookback_days_quant, lookback_days_qual,
                     len(mentions), len(candidate_reports), total_cost, brief_path, db_session_factory)

    elapsed = round(time.time() - t_start, 1)
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
