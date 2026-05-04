"""Report writer agent — LLM polish pass over template-rendered draft."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.agents.base import AgentInput, AgentOutput, BaseAgent

_SYSTEM = """You are a financial research report editor. You receive a draft research report on a company and your job is to:

1. Ensure each section flows naturally and reads like professional research prose.
2. Remove any placeholder text (e.g. "_N/A_", "_No data_") — replace with a brief honest statement of what was unavailable.
3. Ensure the Executive Summary accurately reflects the body of the report.
4. Ensure persona voices are distinct — Burry should sound sceptical, Wood should sound visionary, Lynch should sound pragmatic, Druckenmiller should sound macro-focused.
5. Tighten any wordiness but preserve all specific data points, citations, and source references.
6. Do NOT change verdicts, scores, or recommendations — those come from the analysis agents.
7. Do NOT add information not present in the draft — only reorganise and improve prose.
8. Do NOT add commentary like "As an AI..." or "Note that..." — write as a first-person analyst.

Return the complete polished Markdown report. Begin directly with the # heading."""


class ReportWriterAgent(BaseAgent):
    agent_name = "report_writer"
    llm_role = "report_writer"
    max_output_tokens = 8000

    def run(self, inp: AgentInput) -> AgentOutput:
        system = self._render_system_prompt(inp)
        user = self._render_user_prompt(inp)

        t0 = time.time()
        try:
            text, meta = self._call_llm(system, user)
        except Exception as exc:
            draft = inp.context_data.get("draft", "")
            return AgentOutput(
                agent_name=self.agent_name,
                verdict=None,
                confidence=0.5,
                reasoning=f"LLM polish failed, using raw draft: {exc}",
                key_points=[],
                citations=[],
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=int((time.time() - t0) * 1000),
                raw_response=draft,
                parsed={"text": draft},
            )

        output = AgentOutput(
            agent_name=self.agent_name,
            verdict=None,
            confidence=1.0,
            reasoning="Report polished",
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
        draft = inp.context_data.get("draft", "")
        return f"Polish this research report draft:\n\n{draft}"
