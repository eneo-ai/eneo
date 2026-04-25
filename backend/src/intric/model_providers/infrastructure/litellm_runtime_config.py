"""Process-wide LiteLLM runtime configuration.

LiteLLM prints provider-help text directly to stdout when provider
inference fails. The application uses structured logging; dependency
debug prints should not leak into backend logs or SSE-adjacent output.
"""

from __future__ import annotations

from typing import Any


def configure_litellm_runtime(litellm_module: Any) -> None:
    """Apply application-wide LiteLLM settings idempotently."""
    setattr(litellm_module, "suppress_debug_info", True)


__all__ = ["configure_litellm_runtime"]
