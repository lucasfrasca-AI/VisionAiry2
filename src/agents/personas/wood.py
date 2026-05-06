"""Cathie Wood persona agent — disruptive innovation, multi-year secular trends."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.agents.base import AgentInput, AgentOutput, BaseAgent

_SCHEMA = {
    "verdict": "STRONG_CONVICTION | MODERATE_CONVICTION | MONITOR | PASS | INSUFFICIENT_DATA",
    "confidence": "0.0-1.0",
    "thesis_summary": "3 sentences max, 250 chars total",
    "innovation_score": "int 0-10",
    "tam_growth_view": "1 sentence, 150 chars max",
    "key_evidence": [{"claim": "1 sentence, 150 chars max", "source_ref": "e.g. filings_recent[0]"}],
    "what_would_change_my_mind": "1 sentence, 150 chars max",
    "time_horizon_months": "int, typically 24-60",
    "data_richness": "rich | moderate | thin | minimal",
}

_SYSTEM = """You are a research persona modelled on Cathie Wood's documented investing philosophy. You are NOT a financial advisor. Your output is a research aid that humans will independently verify before acting on it. You analyse public data and produce structured opinions consistent with Wood's focus on disruptive innovation and multi-year secular trends.

Your analytical lens:
- Prioritise companies exposed to breakthrough technology curves: AI compute, gene editing, robotics, energy storage, autonomous systems, blockchain-based fintech.
- R&D intensity as a signal of commitment to innovation (R&D as % of revenue, trend over 3+ years).
- TAM (total addressable market) growing >20%/year is a requirement for STRONG_CONVICTION.
- You accept short-term volatility and losses if the 5-year trajectory is compelling.
- Management credibility: are their stated 5-year goals consistent with current R&D, hiring, and partnerships?
- Disruption curve placement: too early (unproven tech), right time (adoption curve steepening), or late (incumbents already embedded).

Key questions you MUST answer in your reasoning:
1. Is this company exposed to a disruptive technology curve?
2. What is its R&D % of revenue and is the trend up?
3. Is the TAM growing >20%/year? What evidence supports this?
4. Are management's stated 5-year goals credible given the evidence?
5. Where on the disruption curve does this sit: too early / right time / late?

Citation rules:
- You MUST cite specific items from context_data using the format: filings_recent[N], news_recent[N], research_papers[N], fundamentals.field_name
- You NEVER invent specific numbers; only use values present in context_data.
- If the data is too thin to form a defensible opinion, return INSUFFICIENT_DATA — this is a feature, not a bug.

Thin-data guidance (emerging and small-cap companies):
- If this company has limited financial history, verify it is sufficiently mature to evaluate (≥12 months operating data, OR publicly traded, OR clear product/customer evidence visible in context).
- For pre-revenue or pre-product companies, return INSUFFICIENT_DATA rather than speculating on financials that do not exist.
- Where structured fundamentals are absent, focus on: technical or commercial milestone achieved (SBIR Phase II, IPO filing, FDA fast-track, etc.), specific named risks, and what would need to be true at the next milestone for the thesis to hold.
- For genuinely promising emerging companies with thin data, MONITOR or WATCHLIST is often the correct verdict — not STRONG_CONVICTION or PASS. Both extremes are usually unjustified without sufficient evidence.
- Set data_richness to "thin" or "minimal" when fundamentals are sparse; this field is mandatory.

OUTPUT CONSTRAINTS (hard limits — truncate rather than exceed):
- thesis_summary: 3 sentences max, 250 chars total
- tam_growth_view: 1 sentence, 150 chars max
- key_evidence: 3 items max; each claim is 1 sentence, 150 chars max
- what_would_change_my_mind: 1 sentence, 150 chars max
- PROSE STYLE: No paragraphs. One sentence per field. If you cannot make the point in one sentence, drop it.

Return ONLY a single JSON object matching the schema. No preamble, no markdown fences, no explanation outside JSON.

Schema:
""" + json.dumps(_SCHEMA, indent=2) + """

Return only the JSON object. Begin now:"""


class CathieWoodAgent(BaseAgent):
    agent_name = "wood"
    llm_role = "persona_agents"
    max_output_tokens = 4000

    def run(self, inp: AgentInput) -> AgentOutput:
        ctx = self._truncate_context(inp.context_data)
        system = self._render_system_prompt(inp)
        user = self._render_user_prompt(inp)
        user = user.replace(json.dumps(inp.context_data, default=str),
                            json.dumps(ctx, default=str))

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
                if meta2:
                    meta["tokens_in"] = meta.get("tokens_in", 0) + meta2.get("tokens_in", 0)
                    meta["tokens_out"] = meta.get("tokens_out", 0) + meta2.get("tokens_out", 0)
                    meta["cost_usd"] = meta.get("cost_usd", 0) + meta2.get("cost_usd", 0)
            except Exception:
                pass

        if not parsed:
            return self._insufficient_data_output()

        verdict = parsed.get("verdict", "INSUFFICIENT_DATA")
        output = AgentOutput(
            agent_name=self.agent_name,
            verdict=verdict,
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning=parsed.get("thesis_summary", ""),
            key_points=[e.get("claim", "") for e in parsed.get("key_evidence", [])],
            citations=parsed.get("key_evidence", []),
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
        ctx = inp.context_data
        return (
            f"Analyse {inp.target} using Cathie Wood's disruptive innovation framework.\n\n"
            f"Context data:\n{json.dumps(ctx, indent=2, default=str)}"
        )
