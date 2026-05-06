"""Portfolio Manager synthesis agent — final calibrated recommendation."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.agents.base import AgentInput, AgentOutput, BaseAgent

_SCHEMA = {
    "recommendation": "AVOID | WATCHLIST | STARTER | CORE | INSUFFICIENT_DATA",
    "conviction_level": "HIGH | MEDIUM | LOW",
    "time_horizon_months": "int",
    "summary": "str — 3 sentences max, 250 chars total",
    "bull_case_one_liner": "str — 1 sentence, 150 chars max",
    "bear_case_one_liner": "str — 1 sentence, 150 chars max",
    "persona_alignment": {
        "wood": "agrees | disagrees | neutral",
        "druckenmiller": "agrees | disagrees | neutral",
        "burry": "agrees | disagrees | neutral",
        "lynch": "agrees | disagrees | neutral",
    },
    "thesis_breaks_if": "str — 1 specific observable event, 150 chars max",
    "primary_evidence_for": ["str — 3 bullets max, 1 sentence each, 150 chars each"],
    "primary_evidence_against": ["str — 3 bullets max, 1 sentence each, 150 chars each"],
    "confidence": "0.0-1.0",
}

_SYSTEM = """You are a Portfolio Manager synthesis agent. You are NOT a financial advisor. Your output is a research aid for human analysts.

STEP 1 — CLASSIFY EACH PERSONA VERDICT AS BULLISH / NEUTRAL / BEARISH:
  Bullish: Wood(STRONG_CONVICTION, MODERATE_CONVICTION), Druckenmiller(FULL_SIZE, STARTER), Burry(RELUCTANT_LONG), Lynch(STRONG_BUY, BUY)
  Neutral:  Wood(MONITOR), Druckenmiller(MONITOR), Burry(NEUTRAL), Lynch(HOLD)
  Bearish:  Wood(PASS), Druckenmiller(AVOID), Burry(BEAR_CONVICTION, AVOID), Lynch(PASS)

STEP 2 — APPLY SYMMETRIC DECISION TREE (count bullish B, neutral N, bearish X across 4 personas):
  B≥3                      → STARTER (minimum); CORE only if B=4 AND data is rich
  B=2, N≥1, X≤1            → STARTER
  B=2, X=2                  → WATCHLIST
  B≤1, X≥3                  → AVOID
  X≥3                       → AVOID
  All other splits           → WATCHLIST
  Override: ALL 4 personas data_richness in [thin, minimal] → WATCHLIST + LOW regardless

  Do NOT default to AVOID when personas are split. Do NOT let a single high-confidence bearish persona override two bullish personas. Apply the tree literally.

STEP 3 — CONVICTION:
  4 personas same direction → HIGH
  3 personas same direction → MEDIUM
  2 or fewer / split        → LOW
  CRITICAL risk present     → cap at MEDIUM

STEP 4 — thesis_breaks_if must be ONE specific observable event:
  Good: "if Q2 gross margin falls below 45% or FDA issues a CRL"
  Bad:  "if business deteriorates"

OUTPUT CONSTRAINTS (hard limits — truncate rather than exceed):
  summary: 3 sentences max, 250 chars total
  bull_case_one_liner / bear_case_one_liner: 1 sentence, 150 chars max each
  thesis_breaks_if: 1 sentence, 150 chars max
  primary_evidence_for/against: max 3 bullets, 1 sentence each, 150 chars per bullet
  No paragraphs anywhere. No hedged conclusions.

Return ONLY a single JSON object matching the schema. No preamble, no markdown fences.

Schema:
""" + json.dumps(_SCHEMA, indent=2) + """

Return only the JSON object. Begin now:"""


class PortfolioManagerAgent(BaseAgent):
    agent_name = "portfolio_manager"
    llm_role = "report_writer"
    max_output_tokens = 3000

    def run(self, inp: AgentInput) -> AgentOutput:
        ctx = self._truncate_context(inp.context_data)
        system = self._render_system_prompt(inp)
        user = self._render_user_prompt(inp)

        t0 = time.time()
        try:
            text, meta = self._call_llm(system, user)
        except Exception as exc:
            return self._insufficient_data_output(f"LLM call failed: {exc}")

        parsed = self._parse_structured_output(text)
        if not parsed:
            try:
                text2, meta2 = self._call_llm(system, user + "\n\nReturn ONLY valid JSON:")
                parsed = self._parse_structured_output(text2)
            except Exception:
                pass

        if not parsed:
            return self._insufficient_data_output()

        output = AgentOutput(
            agent_name=self.agent_name,
            verdict=parsed.get("recommendation", "INSUFFICIENT_DATA"),
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning=parsed.get("summary", ""),
            key_points=parsed.get("primary_evidence_for", []),
            citations=[],
            tokens_in=meta.get("tokens_in", 0),
            tokens_out=meta.get("tokens_out", 0),
            cost_usd=meta.get("cost_usd", 0.0),
            latency_ms=int((time.time() - t0) * 1000),
            raw_response=text,
            parsed=parsed,
        )

        report_dir = inp.config.get("report_dir")
        if report_dir:
            path = self._save_reasoning(Path(report_dir), system, user, output)
            output.reasoning_path = path

        return output

    def _render_system_prompt(self, inp: AgentInput) -> str:
        return _SYSTEM

    def _render_user_prompt(self, inp: AgentInput) -> str:
        all_outputs = inp.config.get("all_agent_outputs", {})
        ctx = inp.context_data
        return (
            f"Produce the final portfolio manager recommendation for {inp.target}.\n\n"
            f"All upstream agent outputs:\n{json.dumps(all_outputs, indent=2, default=str)}\n\n"
            f"Context data (summary):\n"
            f"Ticker: {ctx.get('ticker')}, Company: {ctx.get('company_name')}, "
            f"Sector: {ctx.get('sector_id')}\n"
            f"Fundamentals: {json.dumps(ctx.get('fundamentals', {}), default=str)}\n"
            f"News count: {len(ctx.get('news_recent', []))}, "
            f"Filings: {len(ctx.get('filings_recent', []))}"
        )
