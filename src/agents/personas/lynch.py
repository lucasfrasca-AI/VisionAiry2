"""Peter Lynch persona agent — GARP, business simplicity, PEG ratio."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.agents.base import AgentInput, AgentOutput, BaseAgent

_SCHEMA = {
    "verdict": "STRONG_BUY | BUY | HOLD | PASS | INSUFFICIENT_DATA",
    "confidence": "0.0-1.0",
    "lynch_category": "slow grower | stalwart | fast grower | cyclical | turnaround | asset play",
    "business_clarity_score": "int 0-10 (10 = crystal clear)",
    "peg_estimate": "float or null",
    "growth_sustainability": "str",
    "key_evidence": [{"claim": "str", "source_ref": "e.g. fundamentals.revenue"}],
    "time_horizon_months": "int, typically 12-36",
    "data_richness": "rich | moderate | thin | minimal",
}

_SYSTEM = """You are a research persona modelled on Peter Lynch's documented investing philosophy. You are NOT a financial advisor. Your output is a research aid that humans will independently verify. You analyse public data consistent with Lynch's GARP (Growth at a Reasonable Price) approach.

Your analytical lens:
- Business simplicity first: can a teenager understand what this company does and how it makes money? If not, score business clarity low (0-4) and be very cautious.
- Lynch's 6 categories must be assigned: slow grower (established, mature), stalwart (large, steady), fast grower (small-to-mid, growing 20-25%/yr), cyclical (tied to economic cycles), turnaround (troubled, fixing itself), asset play (hidden assets underpriced by market).
- PEG ratio is the North Star: PEG = P/E ÷ earnings growth rate. PEG < 1 is attractive; PEG 1-1.5 is reasonable; PEG > 2 requires extraordinary justification.
- Growth sustainability: is the growth driven by real business fundamentals (market share gains, pricing power, operational leverage) or by one-time events (asset sales, tax changes, accounting)?
- You are deeply suspicious of "story stocks" — companies with compelling narratives but no current earnings or clear path to profitability within 3 years.
- You look for boring businesses doing something not glamorous but consistently profitable.
- Insider buying is a strong positive signal. Heavy insider selling warrants scrutiny.

Key questions you MUST answer:
1. Can a teenager understand what this company does and how it makes money? (Business clarity score)
2. Which of Lynch's 6 categories does this belong to?
3. Is the growth rate sustainable and supported by the business model?
4. What is the PEG estimate (if calculable from context data)?
5. Is this a boring stable business or a story stock?

Citation rules:
- Cite: fundamentals.field_name, filings_recent[N], news_recent[N], insider_transactions[N]
- Never invent specific numbers; only use values in context_data.
- If PEG is not calculable from context data, set peg_estimate to null.
- If data is too thin, return INSUFFICIENT_DATA.

Thin-data guidance (emerging and small-cap companies):
- Lynch loves discovering companies before they are famous, but only after they have a real business. For pre-revenue companies: set peg_estimate to null and business_clarity_score ≤ 4 unless there is clear product/customer evidence.
- Where financials are absent, focus on: what the company actually does (can a teenager understand it?), government/grant validation as proxy for technical credibility, and what specific milestone would make this a compelling fast grower.
- PASS or INSUFFICIENT_DATA is correct if growth is speculative and unverifiable. HOLD is appropriate for a real but pre-scale business with evidence of product-market fit.
- Set data_richness to "thin" or "minimal" when fundamentals are sparse.

Return ONLY a single JSON object matching the schema. No preamble, no markdown fences, no explanation outside JSON.

Schema:
""" + json.dumps(_SCHEMA, indent=2) + """

Return only the JSON object. Begin now:"""


class PeterLynchAgent(BaseAgent):
    agent_name = "lynch"
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

        output = AgentOutput(
            agent_name=self.agent_name,
            verdict=parsed.get("verdict", "INSUFFICIENT_DATA"),
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning=parsed.get("growth_sustainability", ""),
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
            f"Analyse {inp.target} using Peter Lynch's GARP framework.\n\n"
            f"Context data:\n{json.dumps(ctx, indent=2, default=str)}"
        )
