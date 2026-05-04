"""DeepSeek adapter via OpenAI-compatible API.

DeepSeek exposes /v1/chat/completions with the same wire format as OpenAI, so we
use the openai client pointed at api.deepseek.com.
"""

from __future__ import annotations

from openai import OpenAI

from src.config import get_config

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _client() -> OpenAI:
    cfg = get_config()
    if not cfg.secrets.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    return OpenAI(api_key=cfg.secrets.DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def complete(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> tuple[str, dict]:
    client = _client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    text = resp.choices[0].message.content or ""
    usage = {
        "input_tokens": getattr(resp.usage, "prompt_tokens", None),
        "output_tokens": getattr(resp.usage, "completion_tokens", None),
    }
    return text, usage


def ping(model: str = "deepseek-chat") -> bool:
    text, _ = complete(model=model, system="Respond with 'pong'.", user="ping",
                       max_tokens=8, temperature=0.0)
    return bool(text)
