"""Completion-model parameter controls.

Explicit persisted capability evidence is the request-shape authority.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, FiniteFloat, ValidationError, model_validator

logger = logging.getLogger(__name__)


class ModelKwargCapability(BaseModel):
    supported: bool = False
    control: Literal["slider", "select"] | None = None
    # Finite bounds, minimum <= maximum, and a finite positive step: a
    # declared range must admit a value.
    minimum: FiniteFloat | None = None
    maximum: FiniteFloat | None = None
    step: FiniteFloat | None = None
    options: list[str] | None = None

    @model_validator(mode="after")
    def _range_admits_a_value(self) -> ModelKwargCapability:
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum must not be greater than maximum")
        if self.step is not None and self.step <= 0:
            raise ValueError("step must be greater than zero")
        return self

    def accepts(self, value: object | None) -> bool:
        """Whether a typed model-setting value is allowed by this capability:
        one of a select's options, or a number within the advertised
        minimum and maximum."""
        if value is None:
            return True
        if not self.supported:
            return False
        if self.control == "select":
            return self.options is not None and value in self.options
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.minimum is not None and value < self.minimum:
                return False
            if self.maximum is not None and value > self.maximum:
                return False
        return True


# How each setting may be offered, following its ModelKwargs type (a test
# pins the two together): a number (float, or int for whole numbers only)
# as a slider; a named level (str) as a select with options. Which levels a
# route offers is its own declaration.
OFFERABLE_MODEL_SETTINGS: dict[str, type[float] | type[int] | type[str]] = {
    "temperature": float,
    "top_p": float,
    "presence_penalty": float,
    "frequency_penalty": float,
    "top_k": int,
    "reasoning_effort": str,
    "verbosity": str,
}


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

    @model_validator(mode="after")
    def _offered_settings_fit_their_type(self) -> SupportedModelKwargs:
        # An offered setting must be declared in a shape that can admit its
        # values; see OFFERABLE_MODEL_SETTINGS.
        for name, kind in OFFERABLE_MODEL_SETTINGS.items():
            capability: ModelKwargCapability = getattr(self, name)
            if not capability.supported:
                continue
            if kind is str:
                if capability.control != "select" or not any(
                    option.strip() for option in capability.options or ()
                ):
                    raise ValueError(
                        f"{name} can be offered only as a select with a non-blank option"
                    )
            elif capability.control != "slider":
                raise ValueError(f"{name} can be offered only as a slider")
            elif kind is int and any(
                bound is not None and not bound.is_integer()
                for bound in (capability.minimum, capability.maximum, capability.step)
            ):
                raise ValueError(f"{name} bounds and step must be whole numbers")
        return self


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


_CapabilityEvidence = Literal[
    "admin_explicit",
    "provider_discovered",
    "catalog_backfill",
]


class _PersistedSupportedModelKwargs(SupportedModelKwargs):
    evidence: _CapabilityEvidence = Field(alias="_evidence")


def _persist_model_kwargs_capabilities(
    capabilities: SupportedModelKwargs,
    *,
    evidence: _CapabilityEvidence,
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


def persist_discovered_model_kwargs_capabilities(
    capabilities: SupportedModelKwargs,
) -> dict[str, object]:
    """Tag a capability snapshot discovered for the exact provider route."""
    return _persist_model_kwargs_capabilities(
        capabilities,
        evidence="provider_discovered",
    )


def _reasoning_effort_select() -> ModelKwargCapability:
    return ModelKwargCapability(
        supported=True,
        control="select",
        options=["low", "medium", "high"],
    )


def reasoning_effort_options_from_model_info(
    model_info: Mapping[str, object],
) -> list[str]:
    """Project LiteLLM reasoning levels, using its standard levels as fallback."""
    if model_info.get("supports_reasoning") is not True:
        return []

    options: list[str] = []
    if model_info.get("supports_none_reasoning_effort") is True:
        options.append("none")
    if model_info.get("supports_minimal_reasoning_effort") is True:
        options.append("minimal")
    if model_info.get("supports_low_reasoning_effort") is not False:
        options.append("low")
    options.extend(("medium", "high"))
    if model_info.get("supports_xhigh_reasoning_effort") is True:
        options.append("xhigh")
    if model_info.get("supports_max_reasoning_effort") is True:
        options.append("max")
    return options


def _default_supported_model_kwargs(*, reasoning: bool) -> SupportedModelKwargs:
    if reasoning:
        return SupportedModelKwargs(reasoning_effort=_reasoning_effort_select())

    return SupportedModelKwargs(
        temperature=_slider_capability(minimum=0, maximum=2, step=0.01)
    )


def snapshot_supported_model_kwargs(
    supported_params: list[str] | None,
    *,
    reasoning: bool,
    reasoning_effort_options: list[str] | None = None,
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
    reasoning_options = (
        reasoning_effort_options
        if reasoning_effort_options is not None
        else ["low", "medium", "high"]
    )
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
                options=reasoning_options,
            )
            if "reasoning_effort" in supported and reasoning_options
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


def _legacy_discovered_snapshot(
    stored: object,
) -> _PersistedSupportedModelKwargs | None:
    """Read a snapshot stored before evidence tags existed.

    Develop stores untagged snapshots, and the pre-release migration that
    tagged them was squashed away. They are provider-discovered records:
    dropping them hides the settings configured against them, and the next
    save erases those. A present `_evidence` key that did not validate is a
    malformed record, not a legacy one.
    """
    if not isinstance(stored, Mapping) or "_evidence" in stored:
        return None
    try:
        return _PersistedSupportedModelKwargs.model_validate(
            {**stored, "_evidence": "provider_discovered"}
        )
    except ValidationError:
        return None


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
            persisted = _legacy_discovered_snapshot(model_kwargs_capabilities)
            if persisted is None:
                logger.warning(
                    "Invalid completion model kwargs capabilities; omitting optional controls",
                    extra={
                        "completion_model_id": str(completion_model_id)
                        if completion_model_id
                        else None,
                        "tenant_id": str(tenant_id) if tenant_id else None,
                    },
                )
                # Fail closed: invalid stored data is a known "no optional
                # controls", never an absent snapshot that discovery may widen.
                return SupportedModelKwargs()

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
