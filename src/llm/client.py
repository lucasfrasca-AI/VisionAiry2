"""Unified LLM entry point.

    complete(role: str, system: str, user: str, **overrides) -> str

Looks up `role` in config.yaml `llm_routing`, dispatches to the matching provider
adapter, falls back on retriable errors, and logs every call to agent_runs.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from src.config import RoleRouting, get_config
from src.llm import claude as _claude
from src.llm import deepseek as _deepseek
from src.llm import gemini as _gemini
from src.llm.fallback import FallbackError, call_with_fallback
from src.storage.db import session_scope
from src.storage.repositories import AgentRunRepo

log = logging.getLogger(__name__)

# provider name -> adapter module
_PROVIDERS: dict[str, Any] = {
    "deepseek": _deepseek,
    "anthropic": _claude,
    "claude": _claude,
    "gemini": _gemini,
    "google": _gemini,
}


def _adapter_call(provider: str, model: str, system: str, user: str,
                  max_tokens: int, temperature: float) -> Callable[[], tuple[str, dict]]:
    if provider not in _PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    mod = _PROVIDERS[provider]

    def _go() -> tuple[str, dict]:
        return mod.complete(
            model=model,
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    return _go


def complete(
    role: str,
    system: str,
    user: str,
    *,
    agent_name: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    log_to_db: bool = True,
) -> str:
    """Call the configured LLM for `role`. Returns the response text.

    Side effect: logs an agent_runs row with {success|fallback|failed}.
    """
    cfg = get_config()
    routing: RoleRouting = cfg.role(role)

    mt = max_tokens if max_tokens is not None else routing.max_tokens
    temp = temperature if temperature is not None else routing.temperature

    primary = _adapter_call(routing.provider, routing.model, system, user, mt, temp)
    fallback = None
    if routing.fallback_provider and routing.fallback_model:
        fallback = _adapter_call(
            routing.fallback_provider, routing.fallback_model, system, user, mt, temp
        )

    started = time.time()
    used_provider = routing.provider
    used_model = routing.model

    def _on_primary_fail(exc: BaseException) -> None:
        nonlocal used_provider, used_model
        log.warning("LLM primary failed for role=%s provider=%s model=%s: %r",
                    role, routing.provider, routing.model, exc)
        used_provider = routing.fallback_provider or routing.provider
        used_model = routing.fallback_model or routing.model

    status = "failed"
    text = ""
    usage: dict[str, Any] = {}
    try:
        text, usage, status = call_with_fallback(primary, fallback, _on_primary_fail)
    except FallbackError as e:
        status = "failed"
        log.error("LLM role=%s failed on both primary and fallback: %s", role, e)
        if log_to_db:
            _record(agent_name or role, role, used_provider, used_model, status,
                    usage, started)
        raise
    except Exception:
        if log_to_db:
            _record(agent_name or role, role, used_provider, used_model, status,
                    usage, started)
        raise

    if log_to_db:
        _record(agent_name or role, role, used_provider, used_model, status, usage, started)
    return text


def _record(agent: str, role: str, provider: str, model: str,
            status: str, usage: dict, started: float) -> None:
    try:
        with session_scope() as s:
            AgentRunRepo(s).log(
                agent_name=agent,
                role=role,
                model=model,
                provider=provider,
                status=status,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                latency_ms=int((time.time() - started) * 1000),
            )
    except Exception as e:
        log.warning("failed to record agent_run: %r", e)
