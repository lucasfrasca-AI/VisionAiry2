"""Provider-agnostic retry/fallback policy.

Triggers fallback on:
  - HTTP 5xx (server error)
  - HTTP 429 (rate limited)
  - Auth errors (401, 403)
  - Generic transport / timeout failures
"""

from __future__ import annotations

import time
from typing import Any, Callable


class FallbackError(Exception):
    """Wraps the underlying exception when an adapter call has failed in a way
    that should trigger fallback to another provider."""


def _looks_like_retriable(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    if any(k in name for k in (
        "rate", "ratelimit", "rate_limit", "overloaded",
        "internal", "server", "timeout", "connection",
        "authentication", "permission", "apistatuserror", "apierror",
    )):
        return True
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(code, int) and (code >= 500 or code in (401, 403, 429)):
        return True
    return False


def call_with_fallback(
    primary: Callable[[], tuple[str, dict]],
    fallback: Callable[[], tuple[str, dict]] | None,
    on_primary_fail: Callable[[BaseException], None] | None = None,
) -> tuple[str, dict, str]:
    """Run primary; if it fails in a retriable way and fallback is provided, run fallback.

    Returns (text, usage, status) where status is "success" or "fallback".
    Raises FallbackError if both fail.
    """
    try:
        text, usage = primary()
        return text, usage, "success"
    except BaseException as e:
        if not _looks_like_retriable(e) and fallback is None:
            raise
        if on_primary_fail:
            try:
                on_primary_fail(e)
            except Exception:
                pass
        if fallback is None:
            raise
        # tiny back-off then fallback
        time.sleep(0.25)
        try:
            text, usage = fallback()
            return text, usage, "fallback"
        except BaseException as e2:
            raise FallbackError(f"primary={e!r}; fallback={e2!r}") from e2
