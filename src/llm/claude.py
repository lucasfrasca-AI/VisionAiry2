"""Anthropic Claude adapter."""

from __future__ import annotations

from anthropic import Anthropic

from src.config import get_config


def _client() -> Anthropic:
    cfg = get_config()
    if not cfg.secrets.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return Anthropic(api_key=cfg.secrets.ANTHROPIC_API_KEY)


def complete(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> tuple[str, dict]:
    client = _client()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    text = "".join(parts)
    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", None),
        "output_tokens": getattr(resp.usage, "output_tokens", None),
    }
    return text, usage


def ping(model: str = "claude-haiku-4-5") -> bool:
    text, _ = complete(model=model, system="Respond with 'pong'.", user="ping",
                       max_tokens=8, temperature=0.0)
    return bool(text)
