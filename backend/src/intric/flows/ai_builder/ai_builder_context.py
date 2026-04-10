from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    resolve_ai_builder_budget_policy,
)
from intric.main.exceptions import BadRequestException
from intric.model_providers.domain.model_defaults import lookup_model_defaults

if TYPE_CHECKING:
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.spaces.space import Space


@dataclass(frozen=True)
class AIBuilderPlannerContext:
    model: "CompletionModel"
    available_models: list[dict[str, str]]
    available_kbs: list[dict[str, str]]
    resource_catalog: AIBuilderResourceCatalog
    max_input_tokens: int
    max_output_tokens: int
    budget_policy: AIBuilderBudgetPolicy


def serialize_space_models(space: "Space") -> list[dict[str, str]]:
    return [
        {
            "id": str(model.id),
            "name": model.name,
            "display_name": model.name,
            "provider": getattr(model, "provider_type", "unknown"),
        }
        for model in getattr(space, "completion_models", [])
    ]


def serialize_space_kbs(space: "Space") -> list[dict[str, str]]:
    return [
        {
            "id": str(collection.id),
            "name": getattr(collection, "name", ""),
            "display_name": getattr(collection, "name", ""),
            "description": getattr(collection, "description", "") or "",
        }
        for collection in getattr(space, "collections", [])
    ]


def resolve_planner_model(space: "Space") -> "CompletionModel":
    model = space.get_default_completion_model()
    if model:
        return model
    if space.completion_models:
        return space.completion_models[0]
    raise BadRequestException(
        "No AI builder planner model is available in this space.",
        code="no_planner_model_available",
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
        raise BadRequestException("Selected model not available in this space")
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
        raise BadRequestException(
            "Planner model is missing a usable context window. Configure max_input_tokens for the model or set an AI Builder fallback in flow settings.",
            code="planner_model_missing_context_window",
        )

    max_output_tokens = getattr(model, "max_output_tokens", None) or (
        defaults.max_output_tokens if defaults else None
    )
    if max_output_tokens is None:
        raise BadRequestException(
            "Planner model is missing max_output_tokens. Configure the model before using AI Builder.",
            code="planner_model_missing_output_tokens",
        )

    available_models = serialize_space_models(space)
    available_kbs = serialize_space_kbs(space)
    return AIBuilderPlannerContext(
        model=model,
        available_models=available_models,
        available_kbs=available_kbs,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=available_models,
            available_kbs=available_kbs,
        ),
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        budget_policy=budget_policy,
    )
