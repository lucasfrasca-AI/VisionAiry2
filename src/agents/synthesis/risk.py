"""Risk inventory agent — specific named risks, not generic filler."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.agents.base import AgentInput, AgentOutput, BaseAgent

_SCHEMA = {
    "risks": [
        {
            "category": "concentration | regulatory | obsolescence | competitive | balance_sheet | key_person | macro",
            "risk_statement": "2 sentences max, 200 chars total — specific, named, cited",
            "severity": "CRITICAL | HIGH | MEDIUM | LOW",
            "evidence_ref": "str e.g. filings_recent[2]",
            "mitigant": "1 sentence max, 150 chars — or null if none identified",
        }
    ],
    "top_3_risks": ["1 sentence each, 150 chars max"],
    "overall_risk_rating": "LOW | MEDIUM | HIGH | CRITICAL",
    "confidence": "0.0-1.0",
}

_SYSTEM = """You are a risk inventory agent. You are NOT a financial advisor. Your output is a research aid for human analysts. Your purpose is to identify SPECIFIC, NAMED risks for the company under analysis — not generic filler.

Risk categories you MUST evaluate:
1. Concentration risks: customer concentration, geographic concentration, product/revenue concentration
2. Regulatory/legal risks: pending litigation, regulatory investigations, compliance exposure
3. Technological obsolescence risks: is the core product threatened by a specific competing technology?
4. Competitive risks: specific named competitors, their advantages, competitive dynamics
5. Balance-sheet/liquidity risks: debt covenants, maturity walls, working capital deterioration, cash burn
6. Key-person/governance risks: founder dependency, board composition, management turnover
7. Macro/cycle risks: specific macro conditions that would hurt this company (rate sensitivity, FX, commodity prices)

STRICT RULES:
- Each risk MUST reference specific evidence from context_data. E.g.: "filings_recent[2] mentions top 3 customers = 47% of revenue"
- Generic risks like "could underperform", "market volatility", "competition could increase" are EXPLICITLY FORBIDDEN.
- If a category has no specific evidence in context_data, omit it. Do NOT invent risks.
- Severity: CRITICAL = existential threat, HIGH = material impact expected, MEDIUM = worth monitoring, LOW = real but unlikely near-term.
- Maximum 8 risks total. Include only the highest-severity risks if more are identified.

OUTPUT CONSTRAINTS (hard limits):
- risk_statement: 2 sentences max, 200 chars total
- mitigant: 1 sentence max, 150 chars — or null
- top_3_risks: 1 sentence each, 150 chars max
- PROSE STYLE: No paragraphs. One sentence per field. Specific numbers > vague statements.

Cite using: filings_recent[N], news_recent[N], fundamentals.field_name, insider_transactions[N]

Return ONLY a single JSON object matching the schema. No preamble, no markdown fences.

Schema:
""" + json.dumps(_SCHEMA, indent=2) + """

Return only the JSON object. Begin now:"""


class RiskInventoryAgent(BaseAgent):
    agent_name = "risk_inventory"
    llm_role = "gap_analysis"
    max_output_tokens = 2000

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
            verdict=parsed.get("overall_risk_rating", "INSUFFICIENT_DATA"),
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning="; ".join(parsed.get("top_3_risks", [])),
            key_points=parsed.get("top_3_risks", []),
            citations=[
                {"claim": r.get("risk_statement", ""), "source_ref": r.get("evidence_ref", "")}
                for r in parsed.get("risks", [])
            ],
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
        persona_outputs = inp.config.get("persona_outputs", {})
        return (
            f"Produce a risk inventory for {inp.target}.\n\n"
            f"Persona analyses (for context):\n{json.dumps(persona_outputs, indent=2, default=str)}\n\n"
            f"Context data:\n{json.dumps(ctx, indent=2, default=str)}"
        )
