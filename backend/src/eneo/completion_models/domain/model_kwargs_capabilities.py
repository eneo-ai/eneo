"""Completion-model parameter controls.

Persisted capability evidence is the request-shape authority. Discovery occurs
when tenant models are created or updated, never while preparing a provider
request.
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


class _PersistedSupportedModelKwargs(SupportedModelKwargs):
    evidence: Literal["admin_explicit", "parameter_presence"] = Field(alias="_evidence")


def _persist_model_kwargs_capabilities(
    capabilities: SupportedModelKwargs,
    *,
    evidence: Literal["admin_explicit", "parameter_presence"],
) -> dict[str, object]:
    persisted = _PersistedSupportedModelKwargs.model_validate(
        {**capabilities.model_dump(), "_evidence": evidence}
    )
    return persisted.model_dump(by_alias=True)


def persist_explicit_model_kwargs_capabilities(
    capabilities: SupportedModelKwargs,
) -> dict[str, object]:
    """Tag admin-authored value-domain evidence before JSONB persistence."""
    return _persist_model_kwargs_capabilities(
        capabilities,
        evidence="admin_explicit",
    )


def persist_parameter_presence_model_kwargs_capabilities(
    capabilities: SupportedModelKwargs,
) -> dict[str, object]:
    """Tag discovery output as non-authoritative before JSONB persistence."""
    return _persist_model_kwargs_capabilities(
        capabilities,
        evidence="parameter_presence",
    )


def snapshot_supported_model_kwargs(
    supported_params: list[str] | None,
    *,
    reasoning: bool,
) -> SupportedModelKwargs:
    """Resolve parameter-name discovery without authorizing value domains.

    LiteLLM reports parameter presence, not which values a route accepts. The
    inputs remain part of the admin-owned discovery interface, but cannot enable
    optional request controls without explicit administrator evidence.
    """
    return SupportedModelKwargs()


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

    if isinstance(model_kwargs_capabilities, _PersistedSupportedModelKwargs):
        persisted = model_kwargs_capabilities
    elif isinstance(model_kwargs_capabilities, SupportedModelKwargs):
        return model_kwargs_capabilities
    else:
        try:
            persisted = _PersistedSupportedModelKwargs.model_validate(
                model_kwargs_capabilities
            )
        except ValidationError:
            try:
                SupportedModelKwargs.model_validate(model_kwargs_capabilities)
            except ValidationError:
                logger.warning(
                    "Invalid completion model kwargs capabilities; omitting optional controls",
                    extra={
                        "completion_model_id": str(completion_model_id)
                        if completion_model_id
                        else None,
                        "tenant_id": str(tenant_id) if tenant_id else None,
                    },
                )
            else:
                logger.warning(
                    "Untagged completion model kwargs capabilities are untrusted; omitting optional controls",
                    extra={
                        "completion_model_id": str(completion_model_id)
                        if completion_model_id
                        else None,
                        "tenant_id": str(tenant_id) if tenant_id else None,
                    },
                )
            return None

    if persisted.evidence != "admin_explicit":
        return None

    return SupportedModelKwargs.model_validate(
        persisted.model_dump(exclude={"evidence"})
    )


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

    return SupportedModelKwargs()
