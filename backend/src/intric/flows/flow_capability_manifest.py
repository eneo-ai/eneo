"""Flow Capability Manifest (FCM) — engine truth about what is possible.

A.0 scope: scaffold only. Declares the `FlowCapability` shape, seeds the
registry with one entry per key in `INPUT_TYPE_POLICIES`, and pins
`FCM_VERSION` to `1`. Rule absorption (chain compatibility, citation,
transcription wizard, etc.) lands in A.1; the public API
(`resolve_capability_for_tuple`, `validate_step_chain`,
`render_critic_invariants`, `coverage_report`) lands in A.6.

Engine-truth only: no Pattern Registry, no AI Builder, no planner prose.
Planner-facing copy and strategy live on the Pattern Registry (A.4) and
Question Catalog (A.4b).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.type_policies import INPUT_TYPE_POLICIES, InputTypePolicy

FCM_VERSION: int = 1

CapabilityId = str
TupleSpec = tuple[FlowInputSource, FlowInputType, FlowOutputType, FlowOutputMode]
Exposure = Literal["builder", "engine_only", "not_exposed"]


@dataclass(frozen=True)
class ConfigRequirement:
    """Named config key this capability requires at runtime.

    Minimum viable shape for A.0. A.1 absorbs concrete requirements from
    `type_policies.py`, `ai_builder_step_capabilities.py`, and the
    transcription / template-fill wizards.
    """

    key: str


@dataclass(frozen=True)
class InvariantSpec:
    """Capability-semantic invariant — must hold whenever the capability is
    in use.

    Minimum viable shape for A.0. A.1 adds concrete invariants lifted from
    `flow_validators.py:66` and `ai_builder_validation_flow_parity.py:55`.
    """

    id: str
    description: str


@dataclass(frozen=True)
class FlowCapability:
    """Engine-truth capability entry.

    `applies_to_tuples`, `required_config`, and `invariants` are empty
    tuples in A.0 — the scaffold carries only the shape and the exposure
    decision. A.1 populates them by absorbing the scattered capability
    rules listed in the plan's FCM scope section.
    """

    id: CapabilityId
    label: str
    description: str
    applies_to_tuples: tuple[TupleSpec, ...]
    required_config: tuple[ConfigRequirement, ...]
    invariants: tuple[InvariantSpec, ...]
    exposure: Exposure
    not_exposed_reason: str | None

    def __post_init__(self) -> None:
        has_reason = bool(self.not_exposed_reason and self.not_exposed_reason.strip())
        if self.exposure != "builder" and not has_reason:
            raise ValueError(
                f"Capability '{self.id}' with exposure='{self.exposure}' "
                "requires a non-empty `not_exposed_reason`."
            )
        if self.exposure == "builder" and has_reason:
            raise ValueError(
                f"Capability '{self.id}' has exposure='builder' but also a "
                "`not_exposed_reason`; engine-truth rejects the contradictory "
                "state — leave `not_exposed_reason=None` for builder exposure."
            )


_UNSUPPORTED_REASONS: dict[str, str] = {
    "image": (
        "Image input is declared unsupported by `INPUT_TYPE_POLICIES['image']` — "
        "no runtime backend accepts raw image bytes for a flow step."
    ),
}


def _seed_input_type_capability(key: str, policy: InputTypePolicy) -> FlowCapability:
    if policy.supported:
        exposure: Exposure = "builder"
        reason: str | None = None
    else:
        exposure = "not_exposed"
        reason = _UNSUPPORTED_REASONS[key]
    return FlowCapability(
        id=f"input_{key}",
        label=f"{key.title()} input",
        description=(
            f"Seeded from `INPUT_TYPE_POLICIES['{key}']` — channel "
            f"'{policy.channel}', contract_allowed={policy.contract_allowed}, "
            f"requires_extraction={policy.requires_extraction}, "
            f"requires_files={policy.requires_files}."
        ),
        applies_to_tuples=(),
        required_config=(),
        invariants=(),
        exposure=exposure,
        not_exposed_reason=reason,
    )


CAPABILITY_REGISTRY: Mapping[CapabilityId, FlowCapability] = MappingProxyType(
    {
        f"input_{key}": _seed_input_type_capability(key, policy)
        for key, policy in INPUT_TYPE_POLICIES.items()
    }
)


# Chain-composition truth: which `(previous_step_output_type, next_step_input_type)`
# pairs are legal when a step is fed by `input_source='previous_step'`. Only
# `previous_step` consults this table — `all_previous_steps` has its own rule
# path in `step_chain_rules.py` (the JSON-over-concatenated-text prohibition)
# and does not participate in type coercion. A.1a mirrors
# `COMPATIBLE_TYPE_COERCIONS` from `step_chain_rules.py` into a typed FCM
# constant so consumers can migrate off the legacy string-tuple table without
# losing the rule. The legacy table stays in place until Phase G deletes it;
# a parity test in `test_flow_capability_manifest.py` enforces lockstep until
# then.
CHAIN_COMPATIBILITY: frozenset[tuple[FlowOutputType, FlowInputType]] = frozenset(
    {
        (FlowOutputType.TEXT, FlowInputType.TEXT),
        (FlowOutputType.TEXT, FlowInputType.JSON),
        (FlowOutputType.TEXT, FlowInputType.ANY),
        (FlowOutputType.JSON, FlowInputType.TEXT),
        (FlowOutputType.JSON, FlowInputType.JSON),
        (FlowOutputType.JSON, FlowInputType.ANY),
        (FlowOutputType.PDF, FlowInputType.TEXT),
        (FlowOutputType.PDF, FlowInputType.ANY),
        (FlowOutputType.DOCX, FlowInputType.TEXT),
        (FlowOutputType.DOCX, FlowInputType.ANY),
    }
)
