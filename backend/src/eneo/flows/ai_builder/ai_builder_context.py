from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.completion_models.domain.model_capacity import (
    CapacityDimension,
    ModelCapacity,
    UnknownModelCapacityError,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContextPolicy,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    translate_unknown_model_capacity,
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

if TYPE_CHECKING:
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.spaces.space import Space


@dataclass(frozen=True)
class AIBuilderPlannerContext:
    model: "CompletionModel"
    available_models: list[AIBuilderAvailableModelResource]
    available_kbs: list[AIBuilderAvailableKnowledgeBaseResource]
    capacity: ModelCapacity
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


def _model_level(model: "CompletionModel") -> int:
    classification = getattr(model, "security_classification", None)
    level = getattr(classification, "security_level", None)
    return level if isinstance(level, int) else 0


def eligible_planner_models(
    space: "Space",
    *,
    active_provider_ids: AbstractSet[UUID],
    minimum_level: int = 0,
) -> list["CompletionModel"]:
    """The planner models a caller may use, listed or sent.

    Three constraints, each already the product's rule elsewhere: the model must
    be accessible, its provider must be active or provider resolution refuses
    it, and it must clear the space's security classification. The last is not
    redundant with the space's own validation — a space validates its models
    when the list is assigned, not when it is loaded, so a stored list outlives
    a reclassification. Since the caller below picks a model on the user's
    behalf, the candidate set is where that has to be caught.

    Listing and sending share this rule, or the session advertises one set of
    models and runs another.

    `minimum_level` is the evidence floor of a turn that reads run evidence:
    a model below the level the runs were recorded at never sees them.
    """
    return [
        model
        for model in space.completion_models
        if model.can_access
        and model.provider_id in active_provider_ids
        and space.allows_model_security_classification(model)
        and _model_level(model) >= minimum_level
    ]


class AIBuilderModelReady(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: Literal["ready"] = "ready"


class AIBuilderModelCapacityUndeclared(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: Literal["capacity_undeclared"] = "capacity_undeclared"
    missing_dimensions: list[CapacityDimension]


class AIBuilderModelCapacityTooSmall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: Literal["capacity_too_small"] = "capacity_too_small"


AIBuilderModelAvailability: TypeAlias = Annotated[
    AIBuilderModelReady
    | AIBuilderModelCapacityUndeclared
    | AIBuilderModelCapacityTooSmall,
    Field(discriminator="state"),
]


def planner_model_availability(
    model: "CompletionModel", *, budget_policy: AIBuilderBudgetPolicy
) -> AIBuilderModelAvailability:
    capacity = model.capacity
    state = capacity.availability(
        safety_tokens=budget_policy.conversation_safety_buffer_tokens
    )
    if state == "capacity_undeclared":
        return AIBuilderModelCapacityUndeclared(
            missing_dimensions=list(capacity.missing_dimensions())
        )
    if state == "capacity_too_small":
        return AIBuilderModelCapacityTooSmall()
    return AIBuilderModelReady()


def select_default_planner_model(
    space: "Space",
    *,
    active_provider_ids: AbstractSet[UUID],
    budget_policy: AIBuilderBudgetPolicy,
    minimum_level: int = 0,
) -> "CompletionModel | None":
    """The model an omitted `model_id` resolves to, or None if there is none.

    The space decides how a default is chosen; the planner only decides which
    models are allowed to be candidates.
    """
    return space.select_default_completion_model(
        [
            model
            for model in eligible_planner_models(
                space,
                active_provider_ids=active_provider_ids,
                minimum_level=minimum_level,
            )
            if planner_model_availability(model, budget_policy=budget_policy).state
            == "ready"
        ]
    )


def resolve_planner_model(
    space: "Space",
    *,
    active_provider_ids: AbstractSet[UUID],
    budget_policy: AIBuilderBudgetPolicy,
    minimum_level: int = 0,
) -> "CompletionModel":
    model = select_default_planner_model(
        space,
        active_provider_ids=active_provider_ids,
        minimum_level=minimum_level,
        budget_policy=budget_policy,
    )
    if model is None:
        raise AIBuilderBadRequestException(
            "No AI builder planner model is available in this space.",
            code=AIBuilderErrorCode.NO_PLANNER_MODEL_AVAILABLE,
            context={"required_level": minimum_level} if minimum_level else None,
        )
    return model


def resolve_requested_model(
    space: "Space",
    *,
    model_id: UUID | None,
    active_provider_ids: AbstractSet[UUID],
    budget_policy: AIBuilderBudgetPolicy,
    minimum_level: int = 0,
) -> "CompletionModel":
    if model_id is None:
        return resolve_planner_model(
            space,
            active_provider_ids=active_provider_ids,
            minimum_level=minimum_level,
            budget_policy=budget_policy,
        )
    candidates = eligible_planner_models(space, active_provider_ids=active_provider_ids)
    model = next(
        (candidate for candidate in candidates if candidate.id == model_id), None
    )
    if model is None:
        raise AIBuilderBadRequestException(
            "Selected model not available in this space",
            code=AIBuilderErrorCode.MODEL_NOT_AVAILABLE,
        )
    if _model_level(model) < minimum_level:
        # The evidence was recorded at a higher level than this model clears;
        # the turn is refused rather than quietly run without its evidence.
        raise AIBuilderBadRequestException(
            "Selected model does not clear the security classification of the run evidence.",
            code=AIBuilderErrorCode.PLANNER_MODEL_BELOW_EVIDENCE_LEVEL,
            context={
                "required_level": minimum_level,
                "model_level": _model_level(model),
            },
        )
    availability = planner_model_availability(model, budget_policy=budget_policy)
    if availability.state == "capacity_undeclared":
        error = UnknownModelCapacityError(tuple(availability.missing_dimensions))
        raise translate_unknown_model_capacity(error) from error
    if availability.state == "capacity_too_small":
        raise AIBuilderBadRequestException(
            "This model's input limit cannot accommodate the configured safety "
            "buffer plus input and an answer. Choose a model with a larger input "
            "limit, or ask an administrator to correct the model limits or safety "
            "buffer policy.",
            code=AIBuilderErrorCode.PLANNER_MODEL_INCOMPATIBLE_TOKEN_LIMITS,
        )
    return model


def build_planner_context(
    space: "Space",
    *,
    active_provider_ids: AbstractSet[UUID],
    model_id: UUID | None = None,
    tenant_flow_settings: dict[str, Any] | None = None,
    minimum_level: int = 0,
) -> AIBuilderPlannerContext:
    budget_policy = resolve_ai_builder_budget_policy(tenant_flow_settings)
    model = resolve_requested_model(
        space,
        model_id=model_id,
        active_provider_ids=active_provider_ids,
        minimum_level=minimum_level,
        budget_policy=budget_policy,
    )
    attachment_context_policy = AIBuilderAttachmentContextPolicy(
        max_template_uncompressed_bytes=(
            budget_policy.max_template_inspection_uncompressed_bytes
        ),
        max_template_placeholders=budget_policy.max_template_placeholders,
    )
    mapped_execution_policy = resolve_flow_mapped_execution_policy(tenant_flow_settings)
    available_models = serialize_space_models(space)
    available_kbs = serialize_space_kbs(space)
    return AIBuilderPlannerContext(
        model=model,
        available_models=available_models,
        available_kbs=available_kbs,
        capacity=model.capacity,
        budget_policy=budget_policy,
        attachment_context_policy=attachment_context_policy,
        mapped_execution_policy=mapped_execution_policy,
    )
