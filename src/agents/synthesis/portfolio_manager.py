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
    "summary": "str (3 sentences)",
    "bull_case_one_liner": "str",
    "bear_case_one_liner": "str",
    "persona_alignment": {
        "wood": "agrees | disagrees | neutral",
        "druckenmiller": "agrees | disagrees | neutral",
        "burry": "agrees | disagrees | neutral",
        "lynch": "agrees | disagrees | neutral",
    },
    "thesis_breaks_if": "str (specific event, not vague)",
    "primary_evidence_for": ["str (top 3 bullet points)"],
    "primary_evidence_against": ["str (top 3 bullet points)"],
    "confidence": "0.0-1.0",
}

_SYSTEM = """You are a Portfolio Manager synthesis agent. You are NOT a financial advisor. Your output is a research aid for human analysts. Your purpose is to read all upstream analysis and produce a calibrated final recommendation.

You receive: four persona outputs (wood, druckenmiller, burry, lynch), gap analysis, risk inventory, and raw context data.

Your decision process:
1. RESOLVE PERSONA DISAGREEMENT EXPLICITLY — name which personas disagree and on what specific point. Do not gloss over disagreement.
2. CALIBRATE CONVICTION honestly:
   - 4 personas aligned + good data = HIGH conviction possible
   - 3/4 aligned + good data = MEDIUM conviction
   - 2/4 or split + thin data = LOW conviction
   - Severe risks or CRITICAL risk rating = cap conviction at MEDIUM regardless of alignment
   - If ALL 4 personas report data_richness in ["thin", "minimal"]: override to WATCHLIST and LOW conviction regardless of individual verdicts — insufficient data for stronger positioning
3. POSITION SIZING:
   - AVOID: do not open a position (risk/reward unfavorable, or bear case dominant)
   - WATCHLIST: monitor; thesis exists but catalyst not yet confirmed or data too thin
   - STARTER: small initial position, scale on confirmation of specific trigger
   - CORE: full conviction, risk understood, asymmetry clear
4. THESIS BREAK CONDITION: define the thesis_breaks_if as a SPECIFIC observable event, not a vague statement.
   BAD: "if business deteriorates"
   GOOD: "if Q2 gross margin falls below 45% or FDA issues a Complete Response Letter"
   For emerging companies: reference specific milestones — "if SBIR Phase II is not followed by a Series B within 18 months" or "if S-1 is withdrawn"

Your summary must:
- Lead with the recommendation and conviction level
- Acknowledge the strongest counterargument
- End with the specific thesis-break condition

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
