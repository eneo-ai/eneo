"""Process-wide LiteLLM runtime configuration.

LiteLLM prints provider-help text directly to stdout when provider
inference fails. The application uses structured logging; dependency
debug prints should not leak into backend logs or SSE-adjacent output.

We also pin the retry and timeout knobs so a future LiteLLM default
change cannot silently expand the budget that the flow runtime's
asyncio.wait_for at `flow_llm_request_timeout_seconds` is supposed
to cap.
"""

from __future__ import annotations

from typing import Any


def configure_litellm_runtime(
    litellm_module: Any,
    *,
    request_timeout_seconds: float | None = None,
) -> None:
    """Apply application-wide LiteLLM settings idempotently.

    When `request_timeout_seconds` is omitted, the LiteLLM HTTP timeout
    follows `settings.flow_llm_request_timeout_seconds` so the asyncio
    budget the flow runtime enforces and the underlying HTTP timeout
    cannot drift apart silently.
    """
    if request_timeout_seconds is None:
        from eneo.main.config import get_settings

        request_timeout_seconds = float(get_settings().flow_llm_request_timeout_seconds)
    setattr(litellm_module, "suppress_debug_info", True)
    setattr(litellm_module, "num_retries", 0)
    setattr(litellm_module, "request_timeout", request_timeout_seconds)


__all__ = ["configure_litellm_runtime"]
