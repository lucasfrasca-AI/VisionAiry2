"""Google Gemini adapter via google-genai SDK."""

from __future__ import annotations

from google import genai
from google.genai import types as genai_types

from src.config import get_config


def _client() -> genai.Client:
    cfg = get_config()
    if not cfg.secrets.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=cfg.secrets.GEMINI_API_KEY)


def complete(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> tuple[str, dict]:
    client = _client()
    resp = client.models.generate_content(
        model=model,
        contents=user,
        config=genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=temperature,
        ),
    )
    text = resp.text or ""
    usage_meta = getattr(resp, "usage_metadata", None)
    usage = {
        "input_tokens": getattr(usage_meta, "prompt_token_count", None) if usage_meta else None,
        "output_tokens": (
            getattr(usage_meta, "candidates_token_count", None) if usage_meta else None
        ),
    }
    return text, usage


def ping(model: str = "gemini-2.5-flash") -> bool:
    text, _ = complete(model=model, system="Respond with 'pong'.", user="ping",
                       max_tokens=8, temperature=0.0)
    return bool(text)
