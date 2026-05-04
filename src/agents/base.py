"""Base agent class for all VisionAiry2 persona and synthesis agents."""
from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class AgentInput:
    target: str
    context_data: dict[str, Any]
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentOutput:
    agent_name: str
    verdict: Optional[str]
    confidence: float
    reasoning: str
    key_points: list[str]
    citations: list[dict[str, Any]]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    reasoning_path: Optional[str] = None
    raw_response: str = ""
    parsed: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    agent_name: str = ""
    llm_role: str = ""
    max_input_tokens: int = 30_000
    max_output_tokens: int = 4_000

    def __init__(self, llm_client: Any, db_session_factory: Any = None) -> None:
        self._llm = llm_client
        self._db = db_session_factory
        self._log = logging.getLogger(f"visionairy2.agents.{self.agent_name}")

    @abstractmethod
    def run(self, inp: AgentInput) -> AgentOutput:
        ...

    @abstractmethod
    def _render_system_prompt(self, inp: AgentInput) -> str:
        ...

    @abstractmethod
    def _render_user_prompt(self, inp: AgentInput) -> str:
        ...

    def _call_llm(self, system: str, user: str) -> tuple[str, dict[str, Any]]:
        from src.llm.client import complete_with_meta
        return complete_with_meta(
            self.llm_role,
            system,
            user,
            agent_name=self.agent_name,
            max_tokens=self.max_output_tokens,
        )

    def _parse_structured_output(self, text: str, schema: dict | None = None) -> dict[str, Any]:
        cleaned = self._strip_fences(text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(cleaned[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return {}

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text.strip(), flags=re.MULTILINE)
        return text.strip()

    def _truncate_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import copy
        ctx = copy.deepcopy(ctx)
        truncation_order = [
            ("news_recent", "raw_payload"),
            ("research_papers", "raw_payload"),
            ("filings_recent", "raw_payload"),
            ("news_recent", "summary"),
            ("research_papers", "summary"),
        ]
        for field_name, subfield in truncation_order:
            items = ctx.get(field_name, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and subfield in item:
                        item.pop(subfield, None)
            json_str = json.dumps(ctx, default=str)
            if len(json_str) // 4 < self.max_input_tokens:
                break
        return ctx

    def _save_reasoning(self, report_dir: Path, system: str, user: str, output: AgentOutput) -> str:
        reasoning_dir = report_dir / "reasoning"
        reasoning_dir.mkdir(parents=True, exist_ok=True)
        path = reasoning_dir / f"{self.agent_name}.md"
        content = f"# {self.agent_name} reasoning\n\n"
        content += "## System Prompt\n\n```\n" + system + "\n```\n\n"
        content += "## User Prompt\n\n```\n" + user + "\n```\n\n"
        content += "## Raw Response\n\n```\n" + output.raw_response + "\n```\n\n"
        content += "## Parsed Output\n\n```json\n" + json.dumps(output.parsed, indent=2) + "\n```\n"
        path.write_text(content)
        return str(path)

    def _log_to_db(self, report_id: str | None, output: AgentOutput) -> None:
        if not self._db:
            return
        try:
            from src.storage.models import AgentRun
            from datetime import datetime, timezone
            from ulid import ULID
            with self._db() as session:
                row = AgentRun(
                    id=str(ULID()),
                    report_id=report_id,
                    agent_name=self.agent_name,
                    role=self.llm_role,
                    model="",
                    provider="",
                    input_tokens=output.tokens_in,
                    output_tokens=output.tokens_out,
                    cost_estimate=output.cost_usd,
                    latency_ms=output.latency_ms,
                    status="success" if output.verdict != "INSUFFICIENT_DATA" else "success",
                    reasoning_path=output.reasoning_path,
                    finished_at=datetime.now(timezone.utc),
                )
                session.add(row)
                session.commit()
        except Exception as exc:
            self._log.warning("DB log failed: %s", exc)

    def _insufficient_data_output(self, reason: str = "Parse failed after retry") -> AgentOutput:
        return AgentOutput(
            agent_name=self.agent_name,
            verdict="INSUFFICIENT_DATA",
            confidence=0.0,
            reasoning=reason,
            key_points=[],
            citations=[],
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=0,
            parsed={"verdict": "INSUFFICIENT_DATA"},
        )
