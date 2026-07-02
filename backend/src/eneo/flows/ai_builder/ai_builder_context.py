from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_mcp_resources import (
    AIBuilderMCPServerResource,
    normalize_ai_builder_mcp_resources,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    resolve_ai_builder_budget_policy,
)
from eneo.model_providers.domain.model_defaults import lookup_model_defaults

if TYPE_CHECKING:
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.spaces.space import Space


@dataclass(frozen=True)
class AIBuilderPlannerContext:
    model: "CompletionModel"
    available_models: list[AIBuilderAvailableModelResource]
    available_kbs: list[AIBuilderAvailableKnowledgeBaseResource]
    available_mcps: list[AIBuilderMCPServerResource]
    max_input_tokens: int
    max_output_tokens: int
    budget_policy: AIBuilderBudgetPolicy


def serialize_space_models(space: "Space") -> list[AIBuilderAvailableModelResource]:
    # `ref` is the local resource id, not the prompt authoring ref.
    return [
        {
            "id": str(model.id),
            "ref": str(model.id),
            "name": model.name,
            "display_name": model.name,
            "provider": getattr(model, "provider_type", "unknown"),
        }
        for model in getattr(space, "completion_models", [])
    ]


def serialize_space_kbs(
    space: "Space",
) -> list[AIBuilderAvailableKnowledgeBaseResource]:
    # `ref` is the local resource id, not the prompt authoring ref.
    return [
        {
            "id": str(collection.id),
            "ref": str(collection.id),
            "name": getattr(collection, "name", ""),
            "display_name": getattr(collection, "name", ""),
            "description": getattr(collection, "description", "") or "",
        }
        for collection in getattr(space, "collections", [])
    ]


def serialize_space_mcps(space: "Space") -> list[AIBuilderMCPServerResource]:
    """Serialize local MCP IDs for catalog allocation, not prompt authoring refs."""
    raw_servers: list[dict[str, Any]] = []
    for server in getattr(space, "mcp_servers", []):
        server_id = getattr(server, "id", None)
        if server_id is None:
            continue
        enabled_tools: list[dict[str, str]] = []
        for tool in getattr(server, "tools", []) or []:
            if not getattr(tool, "is_enabled_by_default", False):
                continue
            tool_id = getattr(tool, "id", None)
            if tool_id is None:
                continue
            enabled_tools.append(
                {
                    "id": str(tool_id),
                    "ref": str(tool_id),
                    "name": getattr(tool, "name", ""),
                    "display_name": getattr(tool, "name", ""),
                    "description": getattr(tool, "description", "") or "",
                }
            )
        if not enabled_tools:
            continue
        raw_servers.append(
            {
                "id": str(server_id),
                "ref": str(server_id),
                "name": getattr(server, "name", ""),
                "display_name": getattr(server, "name", ""),
                "description": getattr(server, "description", "") or "",
                "tools": enabled_tools,
            }
        )
    return normalize_ai_builder_mcp_resources(raw_servers)


def resolve_planner_model(space: "Space") -> "CompletionModel":
    model = space.get_default_completion_model()
    if model:
        return model
    if space.completion_models:
        return space.completion_models[0]
    raise AIBuilderBadRequestException(
        "No AI builder planner model is available in this space.",
        code=AIBuilderErrorCode.NO_PLANNER_MODEL_AVAILABLE,
    )


def resolve_requested_model(
    space: "Space", *, model_id: UUID | None
) -> "CompletionModel":
    if model_id is None:
        return resolve_planner_model(space)

    model = next(
        (
            candidate
            for candidate in getattr(space, "completion_models", [])
            if candidate.id == model_id
        ),
        None,
    )
    if model is None:
        raise AIBuilderBadRequestException(
            "Selected model not available in this space",
            code=AIBuilderErrorCode.MODEL_NOT_AVAILABLE,
        )
    return model


def build_planner_context(
    space: "Space",
    *,
    model_id: UUID | None = None,
    tenant_flow_settings: dict[str, Any] | None = None,
) -> AIBuilderPlannerContext:
    model = resolve_requested_model(space, model_id=model_id)
    defaults = lookup_model_defaults(
        getattr(model, "litellm_model_name", None),
        getattr(model, "name", None),
    )
    budget_policy = resolve_ai_builder_budget_policy(tenant_flow_settings)
    max_input_tokens = (
        getattr(model, "max_input_tokens", None)
        or (defaults.max_input_tokens if defaults else None)
        or budget_policy.unknown_model_context_window_tokens
    )
    if max_input_tokens is None:
        raise AIBuilderBadRequestException(
            "Planner model is missing a usable context window. Configure max_input_tokens for the model or set an AI Builder fallback in flow settings.",
            code=AIBuilderErrorCode.PLANNER_MODEL_MISSING_CONTEXT_WINDOW,
        )

    max_output_tokens = getattr(model, "max_output_tokens", None) or (
        defaults.max_output_tokens if defaults else None
    )
    if max_output_tokens is None:
        raise AIBuilderBadRequestException(
            "Planner model is missing max_output_tokens. Configure the model before using AI Builder.",
            code=AIBuilderErrorCode.PLANNER_MODEL_MISSING_OUTPUT_TOKENS,
        )

    available_models = serialize_space_models(space)
    available_kbs = serialize_space_kbs(space)
    available_mcps = serialize_space_mcps(space)
    return AIBuilderPlannerContext(
        model=model,
        available_models=available_models,
        available_kbs=available_kbs,
        available_mcps=available_mcps,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        budget_policy=budget_policy,
    )
