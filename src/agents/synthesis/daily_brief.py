"""Daily brief writer agent — morning digest from all Mode 1 candidate reports."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.agents.base import AgentInput, AgentOutput, BaseAgent

_SYSTEM = """You are a daily brief writer for a technology and emerging-sector investment research team. You are NOT a financial advisor. Your output is a research aid.

Your brief is the first thing analysts read each morning. It covers what the autonomous discovery scan found overnight.

Voice and style:
- First-person plural: "we found", "we're flagging", "we monitored"
- Lead with the strongest signal, not the most candidates
- Be specific: name companies, cite specific data points, not vague summaries
- Include explicit confidence language: "high conviction", "early-stage signal", "monitoring only", "weak signal — needs confirmation"
- Sector patterns: if multiple candidates share a theme, call it out ("3 of 5 candidates today are in solid-state battery supply chain")
- End with a "What we couldn't research today" section noting source failures, thin-data tickers, or skipped sectors

Structure (MANDATORY):
1. **Top Signal** — the single most interesting finding today (1-2 paragraphs)
2. **Other Candidates** — brief entries for remaining candidates (2-4 sentences each)
3. **Watchlist Alerts** — any urgent updates for existing watchlist tickers (from news_recent, filings)
4. **Sector Pulse** — 1-2 sentences per active sector scanned
5. **What We Couldn't Research Today** — data gaps, source failures, skipped tickers

Length: 400-700 words total.

Return plain Markdown text (no JSON). Begin directly with the heading."""


class DailyBriefWriterAgent(BaseAgent):
    agent_name = "daily_brief"
    llm_role = "daily_brief_writer"
    max_output_tokens = 2000

    def run(self, inp: AgentInput) -> AgentOutput:
        system = self._render_system_prompt(inp)
        user = self._render_user_prompt(inp)

        t0 = time.time()
        try:
            text, meta = self._call_llm(system, user)
        except Exception as exc:
            return self._insufficient_data_output(f"LLM call failed: {exc}")

        output = AgentOutput(
            agent_name=self.agent_name,
            verdict=None,
            confidence=1.0,
            reasoning=text[:200],
            key_points=[],
            citations=[],
            tokens_in=meta.get("tokens_in", 0),
            tokens_out=meta.get("tokens_out", 0),
            cost_usd=meta.get("cost_usd", 0.0),
            latency_ms=int((time.time() - t0) * 1000),
            raw_response=text,
            parsed={"text": text},
        )

        report_dir = inp.config.get("report_dir")
        if report_dir:
            path = self._save_reasoning(Path(report_dir), system, user, output)
            output.reasoning_path = path

        return output

    def _render_system_prompt(self, inp: AgentInput) -> str:
        return _SYSTEM

    def _render_user_prompt(self, inp: AgentInput) -> str:
        ctx = inp.context_data
        candidate_reports = ctx.get("candidate_reports", [])
        watchlist_alerts = ctx.get("watchlist_alerts", [])
        source_failures = ctx.get("source_failures", [])
        sectors_scanned = ctx.get("sectors_scanned", [])

        return (
            f"Date: {ctx.get('date', 'today')}\n"
            f"Sectors scanned: {', '.join(sectors_scanned)}\n\n"
            f"Candidate reports ({len(candidate_reports)} candidates):\n"
            + json.dumps(candidate_reports, indent=2, default=str)
            + f"\n\nWatchlist alerts:\n{json.dumps(watchlist_alerts, indent=2, default=str)}"
            + f"\n\nSource failures: {source_failures}"
        )
