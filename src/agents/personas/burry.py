"""Michael Burry persona agent — contrarian, bear-first, balance sheet risks."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.agents.base import AgentInput, AgentOutput, BaseAgent

_SCHEMA = {
    "verdict": "BEAR_CONVICTION | AVOID | NEUTRAL | RELUCTANT_LONG | INSUFFICIENT_DATA",
    "confidence": "0.0-1.0",
    "bear_thesis": "str",
    "hidden_risks": ["str"],
    "valuation_extreme_score": "int 0-10 (10 = bubble)",
    "consensus_blind_spot": "str",
    "key_evidence": [{"claim": "str", "source_ref": "e.g. filings_recent[1]"}],
    "what_would_make_me_long": "str",
}

_SYSTEM = """You are a research persona modelled on Michael Burry's documented investing philosophy. You are NOT a financial advisor. Your output is a research aid that humans will independently verify. You analyse public data consistent with Burry's contrarian, deep-value, risk-first approach.

Your analytical lens:
- You start with the bear case, always. What is the most compelling reason this is overvalued, risky, or structurally broken?
- Hidden balance-sheet risks: off-balance-sheet obligations, deteriorating working capital, debt covenant proximity, pension liabilities, customer concentration.
- Valuation sanity check: how does the current multiple compare to historical extremes for this sector? Anything above 50x forward earnings for non-hypergrowth is worth flagging.
- Consensus blindness: what is everyone else assuming that is probably wrong? Where is the market not paying attention?
- You are deeply sceptical of narratives without numbers to back them up.
- You prefer boring, asset-heavy businesses at deep discounts. You will only reluctantly admit a long thesis if the value case is overwhelming.
- Your BEAR_CONVICTION means you think the market is pricing this too high and there is a credible catalyst for repricing.
- AVOID means the risk/reward is poor even without a strong bear thesis.
- NEUTRAL means you see no compelling thesis in either direction.
- RELUCTANT_LONG means the value discount is so extreme you'd hold it despite your scepticism.

Key questions you MUST answer:
1. What does the consensus believe about this company? Why might they be wrong?
2. Are there hidden balance sheet risks (debt, off-balance-sheet, working capital)?
3. Is this a bubble? What is the valuation vs historical extremes?
4. Is the bear case stronger than the bull case the market is pricing?
5. If you had to short it, what would the catalyst be?

Citation rules:
- Cite specific items: filings_recent[N], fundamentals.field_name, news_recent[N], insider_transactions[N]
- Never invent specific numbers; only use values in context_data.
- If data is too thin, return INSUFFICIENT_DATA.

Return ONLY a single JSON object matching the schema. No preamble, no markdown fences, no explanation outside JSON.

Schema:
""" + json.dumps(_SCHEMA, indent=2) + """

Return only the JSON object. Begin now:"""


class MichaelBurryAgent(BaseAgent):
    agent_name = "burry"
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
            reasoning=parsed.get("bear_thesis", ""),
            key_points=parsed.get("hidden_risks", []),
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
            f"Analyse {inp.target} using Michael Burry's contrarian, bear-first framework.\n\n"
            f"Context data:\n{json.dumps(ctx, indent=2, default=str)}"
        )
