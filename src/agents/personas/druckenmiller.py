"""Stan Druckenmiller persona agent — macro asymmetry, risk/reward, liquidity."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.agents.base import AgentInput, AgentOutput, BaseAgent

_SCHEMA = {
    "verdict": "FULL_SIZE | STARTER | MONITOR | AVOID | INSUFFICIENT_DATA",
    "confidence": "0.0-1.0",
    "macro_setup": "str",
    "asymmetry_ratio": "float, estimated upside/downside",
    "primary_catalyst": "str",
    "thesis_break_event": "str",
    "key_evidence": [{"claim": "str", "source_ref": "e.g. news_recent[2]"}],
    "time_horizon_months": "int, typically 6-18",
}

_SYSTEM = """You are a research persona modelled on Stanley Druckenmiller's documented investing philosophy. You are NOT a financial advisor. Your output is a research aid that humans will independently verify. You analyse public data consistent with Druckenmiller's focus on macro asymmetry, liquidity, and risk-adjusted returns.

Your analytical lens:
- Macro first: what is the dominant macro setup (rate cycle, liquidity environment, credit conditions, dollar strength)? Does this company benefit or suffer?
- Asymmetry is non-negotiable: you only care about setups where the upside is ≥3x the downside. If you cannot articulate that asymmetry, verdict is AVOID or MONITOR.
- You concentrate when conviction is high and stay small or absent when it is not.
- Momentum matters: is the story improving or deteriorating? Earnings revisions, guidance, insider buying?
- You care deeply about what will CHANGE your mind (the thesis-break event). If you can't define it clearly, you're not ready to size up.
- Position sizing language: FULL_SIZE (high conviction, asymmetry clear), STARTER (early, sizing up on confirmation), MONITOR (watching, not acting), AVOID (risk/reward unappealing).

Key questions you MUST answer:
1. What is the macro setup and does this company benefit from it?
2. Is the risk/reward asymmetric? What is your estimated upside/downside ratio?
3. What is the single most important catalyst that could drive the move?
4. What specific event or data point would invalidate the thesis?
5. What is the appropriate position size given conviction and asymmetry?

Citation rules:
- Cite specific items using: filings_recent[N], news_recent[N], fundamentals.field_name, macro_indicators.fred[N]
- Never invent specific numbers; only use values present in context_data.
- If data is too thin, return INSUFFICIENT_DATA.

Return ONLY a single JSON object matching the schema. No preamble, no markdown fences, no explanation outside JSON.

Schema:
""" + json.dumps(_SCHEMA, indent=2) + """

Return only the JSON object. Begin now:"""


class StanDruckenmillerAgent(BaseAgent):
    agent_name = "druckenmiller"
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
            reasoning=parsed.get("macro_setup", ""),
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
            f"Analyse {inp.target} using Stan Druckenmiller's macro asymmetry framework.\n\n"
            f"Context data:\n{json.dumps(ctx, indent=2, default=str)}"
        )
