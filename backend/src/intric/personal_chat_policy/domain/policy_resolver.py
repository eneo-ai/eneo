# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Pure resolver: maps (assistant, policy, tenant context) -> EffectiveConfig.

This module is intentionally side-effect-free: no DB calls, no awaits.
It is the single source of truth for what is allowed in a personal chat,
and is called from both read paths (UI display) and ask-time runtime
enforcement.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from intric.assistants.assistant import Assistant
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer
    from intric.personal_chat_policy.domain.personal_chat_policy import (
        PersonalChatPolicy,
    )


@dataclass(frozen=True)
class EffectiveConfig:
    models_enforced: bool
    available_models: list["CompletionModel"]
    locked_model: "CompletionModel | None"
    policy_default_model: "CompletionModel | None"

    mcp_enforced: bool
    available_mcp_servers: list["MCPServer"]

    prompt_enforced: bool
    enforced_prompt_text: str | None


_EMPTY = EffectiveConfig(
    models_enforced=False,
    available_models=[],
    locked_model=None,
    policy_default_model=None,
    mcp_enforced=False,
    available_mcp_servers=[],
    prompt_enforced=False,
    enforced_prompt_text=None,
)


def resolve(
    *,
    assistant: "Assistant",
    policy: "PersonalChatPolicy | None",
    tenant_completion_models: list["CompletionModel"],
    tenant_mcp_servers: list["MCPServer"],
    library_prompt_text: str | None,
) -> EffectiveConfig:
    """Compute the effective config for a personal-chat assistant.

    Safe to call for non-default assistants or when no policy exists — in
    those cases all `*_enforced` flags are False, which means "behave as
    before."
    """
    if not assistant.is_default or policy is None:
        return _EMPTY

    # ---- MODELS -----------------------------------------------------------
    available_models: list["CompletionModel"] = []
    locked_model: "CompletionModel | None" = None
    policy_default_model: "CompletionModel | None" = None

    if policy.models_restriction_enabled:
        allowed_ids: set[UUID] = {
            m.completion_model_id for m in policy.completion_models
        }
        # Order: preserve tenant_completion_models order (which the caller
        # controls).
        available_models = [m for m in tenant_completion_models if m.id in allowed_ids]
        if len(available_models) == 1:
            locked_model = available_models[0]

        default_id = next(
            (m.completion_model_id for m in policy.completion_models if m.is_default),
            None,
        )
        if default_id is not None:
            policy_default_model = next(
                (m for m in available_models if m.id == default_id), None
            )

    # ---- MCP --------------------------------------------------------------
    available_mcp_servers: list["MCPServer"] = []
    if policy.mcp_restriction_enabled:
        allowed_mcp_ids: set[UUID] = set(policy.mcp_server_ids)
        available_mcp_servers = [
            s for s in tenant_mcp_servers if s.id in allowed_mcp_ids
        ]

    # ---- PROMPT -----------------------------------------------------------
    # Fail-safe: even if enabled, only inject when text is actually present.
    # Service-level validation prevents this combo, but a stale state must
    # not crash the chat flow.
    enforced_prompt_text: str | None = None
    if policy.prompt_enforcement_enabled and library_prompt_text is not None:
        enforced_prompt_text = library_prompt_text

    return EffectiveConfig(
        models_enforced=policy.models_restriction_enabled,
        available_models=available_models,
        locked_model=locked_model,
        policy_default_model=policy_default_model,
        mcp_enforced=policy.mcp_restriction_enabled,
        available_mcp_servers=available_mcp_servers,
        prompt_enforced=policy.prompt_enforcement_enabled,
        enforced_prompt_text=enforced_prompt_text,
    )
