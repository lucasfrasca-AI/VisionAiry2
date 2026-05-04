"""GAP analysis agent — consensus vs evidence gap finder."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.agents.base import AgentInput, AgentOutput, BaseAgent

_SCHEMA = {
    "consensus_belief": "str",
    "evidence_summary": "str",
    "primary_gap": "str",
    "gap_direction": "OVER_PRICED | UNDER_PRICED | FAIRLY_PRICED | INSUFFICIENT_DATA",
    "counterintuitive_argument": "str",
    "what_would_invalidate_consensus": "str",
    "persona_disagreement_summary": "str",
    "key_evidence": [{"claim": "str", "source_ref": "str"}],
    "confidence": "0.0-1.0",
}

_SYSTEM = """You are a gap analysis agent. You are NOT a financial advisor. Your output is a research aid for human analysts to independently verify. Your purpose is to identify the gap between what the market consensus believes about a company and what the actual evidence shows.

Your method:
- Infer consensus belief from news tone, analyst language in news, and valuation multiples in fundamentals. NEVER invent consensus expectations; only infer from what is in context_data.
- Contrast consensus with evidence: what do the filings, insider transactions, and quantitative data actually show?
- Identify the PRIMARY gap: the most important discrepancy (or alignment) between belief and evidence.
- Produce the strongest possible counterintuitive argument against the dominant persona view.
- Define what specific event or data point would prove the consensus wrong.

You receive: the four persona analyses (wood, druckenmiller, burry, lynch) plus raw context_data.

Critical rules:
- NEVER invent consensus expectations; infer from news_recent and filings_recent only.
- If personas strongly disagree, explicitly name the disagreement and which side has stronger evidence.
- If data is too thin to identify a gap, return gap_direction = "INSUFFICIENT_DATA".
- Cite using: news_recent[N], filings_recent[N], fundamentals.field_name, persona outputs.

Return ONLY a single JSON object matching the schema. No preamble, no markdown fences.

Schema:
""" + json.dumps(_SCHEMA, indent=2) + """

Return only the JSON object. Begin now:"""


class GapAnalysisAgent(BaseAgent):
    agent_name = "gap_analysis"
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
            verdict=parsed.get("gap_direction", "INSUFFICIENT_DATA"),
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning=parsed.get("primary_gap", ""),
            key_points=[parsed.get("counterintuitive_argument", "")],
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
        persona_outputs = inp.config.get("persona_outputs", {})
        ctx = inp.context_data
        return (
            f"Perform gap analysis for {inp.target}.\n\n"
            f"Persona analyses:\n{json.dumps(persona_outputs, indent=2, default=str)}\n\n"
            f"Raw context:\n{json.dumps(ctx, indent=2, default=str)}"
        )
