"""Shared candidate report pipeline — generates a full or lite report for one ticker."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("visionairy2.pipeline")

BUDGET_WARN_USD = 1.50
BUDGET_HARD_USD = 5.00


def generate_candidate_report(
    ticker: str,
    sector_id: str,
    depth: str = "medium",
    db_session_factory: Any = None,
    llm_client: Any = None,
    is_pre_ipo: bool = False,
) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = Path("reports") / ticker / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    from src.agents.context import AgentContextBuilder
    builder = AgentContextBuilder(db_session_factory=db_session_factory)
    ctx = builder.build_for_ticker(ticker, sector_id=sector_id)

    cost_tracker: dict[str, float] = {}
    all_agent_outputs: dict[str, Any] = {}

    if depth == "lite":
        pm_output = _run_portfolio_manager_only(ticker, ctx, {}, {}, report_dir, db_session_factory, llm_client)
        all_agent_outputs["portfolio_manager"] = _output_to_dict(pm_output)
        cost_tracker["portfolio_manager"] = pm_output.cost_usd

        polished = _run_report_writer(
            ticker, ctx, all_agent_outputs, report_dir, db_session_factory, llm_client,
            is_pre_ipo=is_pre_ipo,
        )
        cost_tracker["report_writer"] = polished.cost_usd

        total_cost = sum(cost_tracker.values())
        return _save_and_return(ticker, timestamp, report_dir, ctx, all_agent_outputs,
                                polished, cost_tracker, total_cost, mode=depth)

    # medium depth: all 4 personas + gap + risk + PM + report writer
    total_cost = 0.0

    # Step 1: run 4 personas in parallel
    persona_outputs = _run_personas_parallel(ticker, ctx, report_dir, db_session_factory, llm_client)
    for name, output in persona_outputs.items():
        all_agent_outputs[name] = _output_to_dict(output)
        cost_tracker[name] = output.cost_usd
        total_cost += output.cost_usd
        if total_cost > BUDGET_WARN_USD:
            log.warning("Report cost %.2f exceeds warn threshold $%.2f", total_cost, BUDGET_WARN_USD)

    if total_cost > BUDGET_HARD_USD:
        return _abort_report(ticker, timestamp, report_dir, ctx, all_agent_outputs,
                             total_cost, "Persona agents exceeded budget")

    # Step 2: gap + risk in parallel (both depend on personas)
    gap_out, risk_out = _run_gap_and_risk_parallel(
        ticker, ctx, persona_outputs, report_dir, db_session_factory, llm_client
    )
    all_agent_outputs["gap_analysis"] = _output_to_dict(gap_out)
    all_agent_outputs["risk_inventory"] = _output_to_dict(risk_out)
    cost_tracker["gap_analysis"] = gap_out.cost_usd
    cost_tracker["risk_inventory"] = risk_out.cost_usd
    total_cost += gap_out.cost_usd + risk_out.cost_usd

    if total_cost > BUDGET_HARD_USD:
        return _abort_report(ticker, timestamp, report_dir, ctx, all_agent_outputs,
                             total_cost, "Synthesis agents exceeded budget")

    # Step 3: portfolio manager
    pm_out = _run_portfolio_manager_only(
        ticker, ctx, persona_outputs, {"gap_analysis": gap_out, "risk_inventory": risk_out},
        report_dir, db_session_factory, llm_client
    )
    all_agent_outputs["portfolio_manager"] = _output_to_dict(pm_out)
    cost_tracker["portfolio_manager"] = pm_out.cost_usd
    total_cost += pm_out.cost_usd

    # Step 4: report writer
    polished = _run_report_writer(ticker, ctx, all_agent_outputs, report_dir, db_session_factory, llm_client)
    cost_tracker["report_writer"] = polished.cost_usd
    total_cost += polished.cost_usd

    return _save_and_return(ticker, timestamp, report_dir, ctx, all_agent_outputs,
                            polished, cost_tracker, total_cost, mode=depth)


def _run_personas_parallel(ticker, ctx, report_dir, db_session_factory, llm_client):
    from src.agents.personas.wood import CathieWoodAgent
    from src.agents.personas.druckenmiller import StanDruckenmillerAgent
    from src.agents.personas.burry import MichaelBurryAgent
    from src.agents.personas.lynch import PeterLynchAgent
    from src.agents.base import AgentInput

    agents = {
        "wood": CathieWoodAgent(llm_client, db_session_factory),
        "druckenmiller": StanDruckenmillerAgent(llm_client, db_session_factory),
        "burry": MichaelBurryAgent(llm_client, db_session_factory),
        "lynch": PeterLynchAgent(llm_client, db_session_factory),
    }
    inp = AgentInput(
        target=ticker,
        context_data=ctx,
        config={"report_dir": str(report_dir)},
    )
    results = {}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(agent.run, inp): name for name, agent in agents.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                log.error("Persona %s failed: %s", name, exc)
                from src.agents.base import AgentOutput
                results[name] = AgentOutput(
                    agent_name=name, verdict="INSUFFICIENT_DATA", confidence=0.0,
                    reasoning=str(exc), key_points=[], citations=[],
                    tokens_in=0, tokens_out=0, cost_usd=0.0, latency_ms=0,
                )

    return results


def _run_gap_and_risk_parallel(ticker, ctx, persona_outputs, report_dir, db_session_factory, llm_client):
    from src.agents.synthesis.gap_analysis import GapAnalysisAgent
    from src.agents.synthesis.risk import RiskInventoryAgent
    from src.agents.base import AgentInput

    persona_dicts = {k: _output_to_dict(v) for k, v in persona_outputs.items()}
    gap_inp = AgentInput(
        target=ticker, context_data=ctx,
        config={"report_dir": str(report_dir), "persona_outputs": persona_dicts},
    )
    risk_inp = AgentInput(
        target=ticker, context_data=ctx,
        config={"report_dir": str(report_dir), "persona_outputs": persona_dicts},
    )

    gap_agent = GapAnalysisAgent(llm_client, db_session_factory)
    risk_agent = RiskInventoryAgent(llm_client, db_session_factory)

    with ThreadPoolExecutor(max_workers=2) as pool:
        gap_fut = pool.submit(gap_agent.run, gap_inp)
        risk_fut = pool.submit(risk_agent.run, risk_inp)
        try:
            gap_out = gap_fut.result()
        except Exception as exc:
            gap_out = gap_agent._insufficient_data_output(str(exc))
        try:
            risk_out = risk_fut.result()
        except Exception as exc:
            risk_out = risk_agent._insufficient_data_output(str(exc))

    return gap_out, risk_out


def _run_portfolio_manager_only(ticker, ctx, persona_outputs, extra_outputs, report_dir, db_session_factory, llm_client):
    from src.agents.synthesis.portfolio_manager import PortfolioManagerAgent
    from src.agents.base import AgentInput

    all_outputs = {}
    for k, v in persona_outputs.items():
        all_outputs[k] = _output_to_dict(v) if hasattr(v, "parsed") else v
    for k, v in extra_outputs.items():
        all_outputs[k] = _output_to_dict(v) if hasattr(v, "parsed") else v

    inp = AgentInput(
        target=ticker, context_data=ctx,
        config={"report_dir": str(report_dir), "all_agent_outputs": all_outputs},
    )
    agent = PortfolioManagerAgent(llm_client, db_session_factory)
    try:
        return agent.run(inp)
    except Exception as exc:
        return agent._insufficient_data_output(str(exc))


def _run_report_writer(ticker, ctx, all_agent_outputs, report_dir, db_session_factory, llm_client, is_pre_ipo=False):
    from src.agents.synthesis.report_writer import ReportWriterAgent
    from src.agents.base import AgentInput
    from src.reports.template import render_draft, render_pre_ipo_draft

    if is_pre_ipo:
        draft = render_pre_ipo_draft(ticker, ctx, all_agent_outputs)
    else:
        draft = render_draft(ticker, ctx, all_agent_outputs)
    inp = AgentInput(
        target=ticker,
        context_data={"draft": draft},
        config={"report_dir": str(report_dir)},
    )
    agent = ReportWriterAgent(llm_client, db_session_factory)
    try:
        return agent.run(inp)
    except Exception as exc:
        from src.agents.base import AgentOutput
        return AgentOutput(
            agent_name="report_writer", verdict=None, confidence=0.5,
            reasoning=str(exc), key_points=[], citations=[],
            tokens_in=0, tokens_out=0, cost_usd=0.0, latency_ms=0,
            raw_response=draft, parsed={"text": draft},
        )


def _save_and_return(ticker, timestamp, report_dir, ctx, all_agent_outputs, polished, cost_tracker, total_cost, mode):
    from src.reports.compiler import assemble_report

    polished_text = polished.raw_response if polished else None
    md_path, html_path = assemble_report(ticker, timestamp, all_agent_outputs, ctx, polished_text)

    data_path = report_dir / "data.json"
    data_path.write_text(json.dumps(ctx, indent=2, default=str))

    sources_path = report_dir / "sources.json"
    all_sources = []
    for section in [ctx.get("news_recent", []), ctx.get("filings_recent", []),
                    ctx.get("research_papers", [])]:
        for item in section:
            if item.get("url"):
                all_sources.append({"url": item["url"], "title": item.get("title", ""),
                                    "source": item.get("source", "")})
    sources_path.write_text(json.dumps(all_sources, indent=2))

    cost_path = report_dir / "cost.json"
    cost_path.write_text(json.dumps({
        "total_usd": round(total_cost, 4),
        "per_agent": {k: round(v, 4) for k, v in cost_tracker.items()},
        "timestamp": timestamp,
    }, indent=2))

    pm = all_agent_outputs.get("portfolio_manager", {})
    pm_parsed = pm.get("parsed", {}) if isinstance(pm, dict) else {}

    _save_to_db(ticker, timestamp, md_path, str(data_path), str(sources_path),
                pm_parsed.get("recommendation"), pm_parsed.get("summary", ""))

    log.info("Report generated: %s (cost: $%.4f)", md_path, total_cost)

    return {
        "ticker": ticker,
        "timestamp": timestamp,
        "report_dir": str(report_dir),
        "report_path": md_path,
        "html_path": html_path,
        "cost_usd": round(total_cost, 4),
        "recommendation": pm_parsed.get("recommendation"),
        "conviction": pm_parsed.get("conviction_level"),
        "mode": mode,
    }


def _abort_report(ticker, timestamp, report_dir, ctx, all_agent_outputs, total_cost, reason):
    abort_path = report_dir / "report.md"
    abort_path.write_text(
        f"# {ticker} — Report Aborted\n\n"
        f"**Reason:** {reason}\n\n"
        f"**Total cost at abort:** ${total_cost:.4f}\n\n"
        f"Partial agent outputs saved in data.json.\n"
    )
    data_path = report_dir / "data.json"
    data_path.write_text(json.dumps({"context": ctx, "agents": all_agent_outputs}, default=str))
    return {
        "ticker": ticker,
        "timestamp": timestamp,
        "report_dir": str(report_dir),
        "report_path": str(abort_path),
        "cost_usd": round(total_cost, 4),
        "aborted": True,
        "abort_reason": reason,
    }


def _output_to_dict(output: Any) -> dict:
    if isinstance(output, dict):
        return output
    return {
        "agent_name": output.agent_name,
        "verdict": output.verdict,
        "confidence": output.confidence,
        "reasoning": output.reasoning,
        "key_points": output.key_points,
        "citations": output.citations,
        "tokens_in": output.tokens_in,
        "tokens_out": output.tokens_out,
        "cost_usd": output.cost_usd,
        "latency_ms": output.latency_ms,
        "parsed": output.parsed,
    }


def _save_to_db(ticker, timestamp, report_path, data_path, sources_path, recommendation, summary):
    try:
        from src.storage.db import session_scope
        from src.storage.models import Report
        from ulid import ULID
        from datetime import timezone
        with session_scope() as s:
            row = Report(
                id=str(ULID()),
                ticker=ticker,
                mode="discover",
                generated_at=datetime.now(timezone.utc),
                conviction_level=recommendation,
                recommendation_summary=summary[:500] if summary else None,
                report_path=report_path,
                data_path=data_path,
                sources_path=sources_path,
            )
            s.add(row)
            s.commit()
    except Exception as exc:
        log.warning("DB save failed for report %s: %s", ticker, exc)
