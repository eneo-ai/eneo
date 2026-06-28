"""Completion-model parameter controls.

Resolution order is explicit metadata constrained by core model flags, reasoning
fallback, tenant/LiteLLM sampling controls, then legacy temperature-only
behavior.
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class ModelKwargCapability(BaseModel):
    supported: bool = False
    control: Literal["slider", "select"] | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: list[str] | None = None


class SupportedModelKwargs(BaseModel):
    temperature: ModelKwargCapability = Field(default_factory=ModelKwargCapability)
    top_p: ModelKwargCapability = Field(default_factory=ModelKwargCapability)
    reasoning_effort: ModelKwargCapability = Field(default_factory=ModelKwargCapability)
    verbosity: ModelKwargCapability = Field(default_factory=ModelKwargCapability)
    presence_penalty: ModelKwargCapability = Field(default_factory=ModelKwargCapability)
    frequency_penalty: ModelKwargCapability = Field(
        default_factory=ModelKwargCapability
    )
    top_k: ModelKwargCapability = Field(default_factory=ModelKwargCapability)


def _slider_capability(
    *, minimum: float, maximum: float, step: float
) -> ModelKwargCapability:
    return ModelKwargCapability(
        supported=True,
        control="slider",
        minimum=minimum,
        maximum=maximum,
        step=step,
    )


def _reasoning_effort_select() -> ModelKwargCapability:
    return ModelKwargCapability(
        supported=True,
        control="select",
        options=["low", "medium", "high"],
    )


def _default_supported_model_kwargs(*, reasoning: bool) -> SupportedModelKwargs:
    if reasoning:
        return SupportedModelKwargs(reasoning_effort=_reasoning_effort_select())

    return SupportedModelKwargs(
        temperature=_slider_capability(minimum=0, maximum=2, step=0.01)
    )


def _tenant_supported_model_kwargs() -> SupportedModelKwargs:
    return SupportedModelKwargs(
        temperature=_slider_capability(minimum=0, maximum=2, step=0.01),
        top_p=_slider_capability(minimum=0, maximum=1, step=0.01),
        presence_penalty=_slider_capability(minimum=-2, maximum=2, step=0.1),
        frequency_penalty=_slider_capability(minimum=-2, maximum=2, step=0.1),
        top_k=ModelKwargCapability(
            supported=True,
            control="slider",
            minimum=1,
            maximum=100,
            step=1,
        ),
    )


def snapshot_supported_model_kwargs(
    supported_params: list[str] | None,
    *,
    reasoning: bool,
) -> SupportedModelKwargs:
    """Convert LiteLLM discovery data into persisted Eneo capabilities.

    This is intended for model creation/update, not request-time lookup. The
    resulting snapshot keeps UI and execution behavior stable across dependency
    upgrades.

    `reasoning` is the admin-declared model flag. It must be honored here:
    discovery is name-based, so opaque routes (e.g. Azure deployment names)
    miss reasoning support entirely, and the persisted snapshot acts as an
    explicit override at resolve time which is never widened again.
    """
    if supported_params is None:
        return _default_supported_model_kwargs(reasoning=reasoning)

    supported = set(supported_params)
    snapshot = SupportedModelKwargs(
        temperature=(
            _slider_capability(minimum=0, maximum=2, step=0.01)
            if "temperature" in supported
            else ModelKwargCapability()
        ),
        top_p=(
            _slider_capability(minimum=0, maximum=1, step=0.01)
            if "top_p" in supported
            else ModelKwargCapability()
        ),
        reasoning_effort=(
            ModelKwargCapability(
                supported=True,
                control="select",
                options=["none", "low", "medium", "high"],
            )
            if "reasoning_effort" in supported
            else ModelKwargCapability()
        ),
        verbosity=(
            ModelKwargCapability(
                supported=True,
                control="select",
                options=["low", "medium", "high"],
            )
            if "verbosity" in supported
            else ModelKwargCapability()
        ),
        presence_penalty=(
            _slider_capability(minimum=-2, maximum=2, step=0.1)
            if "presence_penalty" in supported
            else ModelKwargCapability()
        ),
        frequency_penalty=(
            _slider_capability(minimum=-2, maximum=2, step=0.1)
            if "frequency_penalty" in supported
            else ModelKwargCapability()
        ),
        top_k=(
            ModelKwargCapability(
                supported=True,
                control="slider",
                minimum=1,
                maximum=100,
                step=1,
            )
            if "top_k" in supported
            else ModelKwargCapability()
        ),
    )
    if reasoning and not snapshot.reasoning_effort.supported:
        snapshot = snapshot.model_copy(
            update={"reasoning_effort": _reasoning_effort_select()}
        )
    return snapshot


def _apply_model_capability_flags(
    supported_model_kwargs: SupportedModelKwargs,
    *,
    reasoning: bool,
) -> SupportedModelKwargs:
    if reasoning:
        return supported_model_kwargs

    return supported_model_kwargs.model_copy(
        update={"reasoning_effort": ModelKwargCapability()}
    )


def coerce_model_kwargs_capabilities(
    model_kwargs_capabilities: object | None,
    *,
    completion_model_id: UUID | None,
    tenant_id: UUID | None,
) -> SupportedModelKwargs | None:
    if model_kwargs_capabilities is None:
        return None

    if isinstance(model_kwargs_capabilities, SupportedModelKwargs):
        return model_kwargs_capabilities

    try:
        return SupportedModelKwargs.model_validate(model_kwargs_capabilities)
    except ValidationError:
        logger.warning(
            "Invalid completion model kwargs capabilities; using default fallback",
            extra={
                "completion_model_id": str(completion_model_id)
                if completion_model_id
                else None,
                "tenant_id": str(tenant_id) if tenant_id else None,
            },
        )
        return None


def resolve_supported_model_kwargs(
    *,
    model_kwargs_capabilities: object | None = None,
    reasoning: bool,
    provider_type: str | None = None,
    litellm_model_name: str | None = None,
    completion_model_id: UUID | None = None,
    tenant_id: UUID | None = None,
) -> SupportedModelKwargs:
    override = coerce_model_kwargs_capabilities(
        model_kwargs_capabilities,
        completion_model_id=completion_model_id,
        tenant_id=tenant_id,
    )
    if override is not None:
        return _apply_model_capability_flags(override, reasoning=reasoning)

    if reasoning:
        return _apply_model_capability_flags(
            _default_supported_model_kwargs(reasoning=reasoning),
            reasoning=reasoning,
        )

    # Tenant models run through LiteLLM with drop_params=True, so this contract
    # can expose the common sampling controls without duplicating provider
    # support tables in the frontend.
    if provider_type or litellm_model_name:
        return _apply_model_capability_flags(
            _tenant_supported_model_kwargs(),
            reasoning=reasoning,
        )

    return _apply_model_capability_flags(
        _default_supported_model_kwargs(reasoning=reasoning),
        reasoning=reasoning,
    )
