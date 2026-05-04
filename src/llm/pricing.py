"""Per-token pricing table for cost estimation."""
from __future__ import annotations

_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # model_id: (input_usd_per_mtok, output_usd_per_mtok)
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "gemini-2.5-flash": (0.15, 3.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _PRICE_PER_MTOK.get(model, (1.00, 5.00))
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
