# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Pure resolver: maps (assistant, scope, policy, tenant context) -> EffectiveConfig.

This module is intentionally side-effect-free: no DB calls, no awaits.
It is the single source of truth for what is allowed in a personal assistant,
and is called from both read paths (UI display) and ask-time runtime
enforcement.
"""

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from intric.assistants.assistant import Assistant
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.governance_policy.domain.governance_policy import (
        GovernancePolicy,
    )
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer


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

    # Allowed servers that start switched OFF in the user's chat (UX seed
    # only — the user can still enable them per conversation).
    default_disabled_mcp_server_ids: list[UUID] = field(
        default_factory=lambda: []  # noqa: C408
    )


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
    space_is_personal: bool,
    policy: "GovernancePolicy | None",
    tenant_completion_models: list["CompletionModel"],
    tenant_mcp_servers: list["MCPServer"],
    library_prompt_text: str | None,
) -> EffectiveConfig:
    """Compute the effective config for a personal assistant.

    Safe to call for non-default assistants, non-personal spaces, or when no
    policy exists — in those cases all `*_enforced` flags are False, which
    means "behave as before."
    """
    if not assistant.is_default or not space_is_personal or policy is None:
        return _EMPTY

    # ---- MODELS -----------------------------------------------------------
    available_models: list["CompletionModel"] = []
    locked_model: "CompletionModel | None" = None
    policy_default_model: "CompletionModel | None" = None

    if policy.models_restriction_enabled:
        explicit_ids: set[UUID] = {
            m.completion_model_id for m in policy.completion_models
        }
        provider_ids: set[UUID] = set(policy.model_provider_ids)
        # Order: preserve tenant_completion_models order (which the caller
        # controls). A model is available if explicitly whitelisted OR if
        # its provider is whitelisted — the latter is "subscribe to all
        # current and future models from this provider."
        available_models = [
            m
            for m in tenant_completion_models
            if m.id in explicit_ids
            or (m.provider_id is not None and m.provider_id in provider_ids)
        ]
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
    default_disabled_mcp_server_ids: list[UUID] = []
    if policy.mcp_restriction_enabled:
        allowed_mcp_ids: set[UUID] = {e.mcp_server_id for e in policy.mcp_servers}
        disabled_tool_ids: set[UUID] = set(policy.disabled_mcp_tool_ids)
        for server in tenant_mcp_servers:
            if server.id not in allowed_mcp_ids:
                continue
            if disabled_tool_ids and any(
                t.id in disabled_tool_ids for t in server.tools
            ):
                # Shallow-copy before narrowing tools: the entity instance is
                # shared with other readers in the same request, and both the
                # chat UI serialization and the MCP proxy registry consume
                # `available_mcp_servers[].tools` as the allowed set.
                server = copy.copy(server)
                server.tools = [
                    t for t in server.tools if t.id not in disabled_tool_ids
                ]
            available_mcp_servers.append(server)
        available_ids = {s.id for s in available_mcp_servers}
        default_disabled_mcp_server_ids = [
            e.mcp_server_id
            for e in policy.mcp_servers
            if not e.is_default_enabled and e.mcp_server_id in available_ids
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
        default_disabled_mcp_server_ids=default_disabled_mcp_server_ids,
        prompt_enforced=policy.prompt_enforcement_enabled,
        enforced_prompt_text=enforced_prompt_text,
    )


def select_effective_completion_model(
    current_model: "CompletionModel | None",
    effective_config: "EffectiveConfig | None",
) -> "CompletionModel | None":
    """The completion model that will actually answer, honoring a models policy.

    Single source of truth shared by ask-time enforcement and read-time
    preflight so the two can never disagree about which model a request will
    use:

    - No policy enforcing models → the assistant's own `current_model`.
    - Models enforced and `current_model` is allowed → keep it.
    - Models enforced and `current_model` is missing/stale → fall back to the
      policy default, then the first allowed model.

    Returns None only when nothing is available (an enforced policy with an
    empty whitelist, or no model configured at all). Callers decide whether
    that is an error.
    """
    if effective_config is None or not effective_config.models_enforced:
        return current_model

    allowed_ids = {model.id for model in effective_config.available_models}
    if current_model is not None and current_model.id in allowed_ids:
        return current_model

    return effective_config.policy_default_model or (
        effective_config.available_models[0]
        if effective_config.available_models
        else None
    )
