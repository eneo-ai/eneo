from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContextPolicy,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    resolve_ai_builder_budget_policy,
)
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    resolve_flow_mapped_execution_policy,
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
    max_input_tokens: int
    max_output_tokens: int
    budget_policy: AIBuilderBudgetPolicy
    attachment_context_policy: AIBuilderAttachmentContextPolicy
    mapped_execution_policy: FlowMappedExecutionPolicy


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


def eligible_planner_models(
    space: "Space", *, active_provider_ids: AbstractSet[UUID]
) -> list["CompletionModel"]:
    """The planner models a caller may use, listed or sent.

    A model on an inactive provider is rejected at provider resolution, so it is
    not eligible here either. Listing and sending must share this rule, or the
    session advertises one set of models and runs another.
    """
    return [
        model
        for model in getattr(space, "completion_models", [])
        if model.provider_id in active_provider_ids
    ]


def select_default_planner_model(
    space: "Space", *, active_provider_ids: AbstractSet[UUID]
) -> "CompletionModel | None":
    """The model an omitted `model_id` resolves to, or None if there is none."""
    eligible = eligible_planner_models(space, active_provider_ids=active_provider_ids)
    configured_default = space.get_default_completion_model()
    if configured_default is not None and any(
        model.id == configured_default.id for model in eligible
    ):
        return configured_default
    return eligible[0] if eligible else None


def resolve_planner_model(
    space: "Space", *, active_provider_ids: AbstractSet[UUID]
) -> "CompletionModel":
    model = select_default_planner_model(space, active_provider_ids=active_provider_ids)
    if model is None:
        raise AIBuilderBadRequestException(
            "No AI builder planner model is available in this space.",
            code=AIBuilderErrorCode.NO_PLANNER_MODEL_AVAILABLE,
        )
    return model


def resolve_requested_model(
    space: "Space",
    *,
    model_id: UUID | None,
    active_provider_ids: AbstractSet[UUID],
) -> "CompletionModel":
    if model_id is None:
        return resolve_planner_model(space, active_provider_ids=active_provider_ids)

    model = next(
        (
            candidate
            for candidate in eligible_planner_models(
                space, active_provider_ids=active_provider_ids
            )
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
    active_provider_ids: AbstractSet[UUID],
    model_id: UUID | None = None,
    tenant_flow_settings: dict[str, Any] | None = None,
) -> AIBuilderPlannerContext:
    model = resolve_requested_model(
        space, model_id=model_id, active_provider_ids=active_provider_ids
    )
    defaults = lookup_model_defaults(
        getattr(model, "litellm_model_name", None),
        getattr(model, "name", None),
    )
    budget_policy = resolve_ai_builder_budget_policy(tenant_flow_settings)
    attachment_context_policy = AIBuilderAttachmentContextPolicy(
        max_template_uncompressed_bytes=(
            budget_policy.max_template_inspection_uncompressed_bytes
        ),
        max_template_placeholders=budget_policy.max_template_placeholders,
    )
    mapped_execution_policy = resolve_flow_mapped_execution_policy(tenant_flow_settings)
    max_input_tokens = getattr(model, "max_input_tokens", None) or (
        defaults.max_input_tokens if defaults else None
    )
    if max_input_tokens is None:
        raise AIBuilderBadRequestException(
            "Planner model is missing a usable context window. Configure max_input_tokens for the model.",
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
    return AIBuilderPlannerContext(
        model=model,
        available_models=available_models,
        available_kbs=available_kbs,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        budget_policy=budget_policy,
        attachment_context_policy=attachment_context_policy,
        mapped_execution_policy=mapped_execution_policy,
    )
