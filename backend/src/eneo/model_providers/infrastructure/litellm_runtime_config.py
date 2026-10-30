"""Process-wide LiteLLM runtime configuration.

LiteLLM prints provider-help text directly to stdout when provider
inference fails. The application uses structured logging; dependency
debug prints should not leak into backend logs or SSE-adjacent output.

Retries are disabled and requests outside a flow attempt use the deployment
runtime policy as their default timeout. Flow requests supply their remaining
attempt budget at the request boundary.
"""

from __future__ import annotations

from typing import Any


def configure_litellm_runtime(
    litellm_module: Any,
    *,
    request_timeout_seconds: float | None = None,
) -> None:
    """Apply application-wide LiteLLM settings idempotently.

    When omitted, the process default follows the deployment runtime policy.
    A flow attempt overrides it per request with its remaining effective budget.
    """
    if request_timeout_seconds is None:
        from eneo.flows.flow_runtime_policy import default_flow_runtime_policy

        request_timeout_seconds = float(
            default_flow_runtime_policy().default_step_timeout_seconds
        )
    setattr(litellm_module, "suppress_debug_info", True)
    setattr(litellm_module, "num_retries", 0)
    setattr(litellm_module, "request_timeout", request_timeout_seconds)


__all__ = ["configure_litellm_runtime"]
