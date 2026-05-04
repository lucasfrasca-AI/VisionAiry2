"""Mode 3: Document analysis."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("visionairy2.analyse_doc")


def analyse_document(
    url_or_path: str,
    db_session_factory: Any = None,
    llm_client: Any = None,
    progress_cb=None,
) -> dict[str, Any]:
    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)
        else:
            log.info(msg)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = Path("reports") / "_doc_analysis_" / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    _emit(f"[analyse_doc] Processing: {url_or_path}")

    from src.agents.context import AgentContextBuilder
    builder = AgentContextBuilder(db_session_factory=db_session_factory)
    doc_ctx = builder.build_for_document(url_or_path)

    _emit(f"[analyse_doc] Extracted {len(doc_ctx.get('raw_text', ''))} chars of text")
    _emit(f"[analyse_doc] Found entities: {[e.get('name') for e in doc_ctx.get('extracted_entities', [])[:5]]}")

    # Resolve tickers from extracted entities
    tickers_found: list[str] = []
    from src.ingestion.ticker_resolver import TickerResolver
    from src.llm.client import complete as _llm_complete
    _llm_shim = type("_LLM", (), {"complete": staticmethod(_llm_complete)})()
    resolver = TickerResolver(db_session_factory=db_session_factory, llm_client=_llm_shim)
    for entity in doc_ctx.get("extracted_entities", [])[:10]:
        name = entity.get("name", "")
        if name:
            try:
                ticker = resolver.resolve(name)
                if ticker and ticker not in tickers_found:
                    tickers_found.append(ticker)
            except Exception:
                pass

    _emit(f"[analyse_doc] Resolved tickers: {tickers_found}")

    # Run lite pipeline for each ticker (max 5)
    from src.modes._pipeline import generate_candidate_report
    ticker_results = []
    total_cost = 0.0

    for ticker in tickers_found[:5]:
        _emit(f"[analyse_doc] Analysing {ticker} (lite mode)")
        try:
            result = generate_candidate_report(
                ticker=ticker,
                sector_id="ai_software",
                depth="lite",
                db_session_factory=db_session_factory,
                llm_client=llm_client,
            )
            ticker_results.append(result)
            total_cost += result.get("cost_usd", 0.0)
        except Exception as exc:
            log.error("Lite report failed for %s: %s", ticker, exc)
            ticker_results.append({"ticker": ticker, "error": str(exc)})

    # Generate combined doc analysis report
    combined_md = _generate_doc_report(url_or_path, doc_ctx, ticker_results, timestamp)
    report_path = report_dir / "report.md"
    report_path.write_text(combined_md)

    _emit(f"[analyse_doc] Report written to {report_path}")

    return {
        "url_or_path": url_or_path,
        "timestamp": timestamp,
        "report_dir": str(report_dir),
        "report_path": str(report_path),
        "tickers_found": tickers_found,
        "ticker_count": len(ticker_results),
        "total_cost_usd": round(total_cost, 4),
    }


def _generate_doc_report(url_or_path: str, doc_ctx: dict, ticker_results: list, timestamp: str) -> str:
    title = doc_ctx.get("title", url_or_path)
    raw_text = doc_ctx.get("raw_text", "")
    entities = doc_ctx.get("extracted_entities", [])

    lines = [
        f"# Document Analysis: {title}",
        f"",
        f"**Analysed:** {timestamp}",
        f"**Source:** {url_or_path}",
        f"",
        f"> *Research aid only — not financial advice.*",
        f"",
        f"---",
        f"",
        f"## Document Summary",
        f"",
        raw_text[:500] + ("..." if len(raw_text) > 500 else ""),
        f"",
        f"---",
        f"",
        f"## Entities Mentioned",
        f"",
    ]

    for e in entities[:10]:
        name = e.get("name", "")
        ticker = e.get("ticker", "")
        context = e.get("context", "")
        lines.append(f"- **{name}**{f' ({ticker})' if ticker else ''}{f': {context}' if context else ''}")

    lines += ["", "---", "", "## Company Analyses", ""]

    for res in ticker_results:
        ticker = res.get("ticker", "?")
        if res.get("error"):
            lines.append(f"### {ticker}\n\n_Analysis failed: {res['error']}_\n")
            continue
        rp = res.get("report_path", "")
        recommendation = res.get("recommendation", "N/A")
        conviction = res.get("conviction", "N/A")
        lines.append(f"### {ticker}")
        lines.append(f"**Recommendation:** {recommendation} | **Conviction:** {conviction}")
        if rp and Path(rp).exists():
            excerpt = Path(rp).read_text()[:800]
            lines.append(f"\n{excerpt}\n\n[Full report]({rp})\n")

    lines += ["", "---", "", "## What to Watch", ""]
    lines.append("- Review the entities mentioned in this document for new signals.")
    lines.append("- Cross-reference with recent SEC filings for named companies.")
    lines.append("- Check if any mentioned technologies align with watchlist sector themes.")

    return "\n".join(lines)
