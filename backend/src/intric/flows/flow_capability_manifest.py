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

Versioning discipline: `FCM_VERSION` is the monotonic integer stamped on
persisted plans, planning-state snapshots, and digests starting in Phase
C. Phase A (A.0–A.6) is an unpublished epoch — no consumer reads the
version yet, so capability-surface changes during Phase A do not bump
`FCM_VERSION`. Phase A ends with `FCM_VERSION=1`; the first bump lands
when a later consumer begins persisting the version. After that, any
capability-surface change — new registry key, added/changed
`applies_to_tuples`, added/changed `FlowCapability` / nested-type field,
or altered `invariants` content — bumps the version and keeps any retired
capability resolvable with a deprecation reason for one bump cycle.

A.3's bump-discipline CI test must cover this full surface; the plan's
original narrow spec (keys + `applies_to_tuples`) misses field additions
and invariant-content changes. A.3 widens it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from intric.flows.citation_sidecar import (
    CITATION_MODE_INLINE_INREF_SIDECAR,
    resolve_citation_mode,
)
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
Channel = Literal["text_only", "files_only"]
RuntimeInputMode = Literal["documents", "audio", "text"]
OutputArtifact = Literal[
    "structured_text", "structured_json", "pdf_document", "docx_document"
]
DocumentGenerationMode = Literal["generated", "template_fill"]


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
    channel: Channel | None = None
    runtime_input_mode: RuntimeInputMode | None = None

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
        if self.id.startswith("input_") and self.channel is None:
            raise ValueError(
                f"Capability '{self.id}' is an input capability but has "
                "`channel=None`; every input capability must declare its channel."
            )


_UNSUPPORTED_REASONS: dict[str, str] = {
    "image": (
        "Image input is declared unsupported by `INPUT_TYPE_POLICIES['image']` — "
        "no runtime backend accepts raw image bytes for a flow step."
    ),
}


# Mirrors `BUILDER_RUNTIME_INPUT_MODE_BY_INPUT_TYPE` in
# `ai_builder/ai_builder_step_capabilities.py`. Engine-truth cannot import
# from `ai_builder` (P0.7 boundary), so the mapping is duplicated here and
# held in lockstep by a parity test until Phase G deletes the ai_builder
# copy. `image` and `any` are intentionally absent — the runtime has no
# input_mode for those keys, and a capability without a runtime_input_mode
# simply carries `None`.
_RUNTIME_INPUT_MODE_BY_KEY: dict[str, RuntimeInputMode] = {
    "document": "documents",
    "file": "documents",
    "audio": "audio",
    "text": "text",
    "json": "text",
}


def _narrow_channel(key: str, raw: str) -> Channel:
    """Narrow `InputTypePolicy.channel` (`str`) into the FCM `Channel` literal.

    Fail-loud on drift so a new channel value in `type_policies.py` can't
    silently pass through the FCM seeder without a matching update here.
    """
    if raw == "text_only":
        return "text_only"
    if raw == "files_only":
        return "files_only"
    raise ValueError(
        f"INPUT_TYPE_POLICIES['{key}'].channel has unknown value {raw!r}; "
        "FCM expects 'text_only' or 'files_only'."
    )


def _absorbed_invariants(
    key: str, policy: InputTypePolicy
) -> tuple[InvariantSpec, ...]:
    """Mirror the three runtime rules on `InputTypePolicy` as FCM invariants.

    Rules are the ones enforced by `flow_validators.validate_steps` and
    `runtime.step_input_validation.validate_runtime_input_policy`. The
    `supported` flag is handled upstream via `exposure`; the `channel`
    field is a capability attribute, not a runtime rule, and is mirrored
    separately on `FlowCapability.channel`.
    """
    invariants: list[InvariantSpec] = []
    if not policy.contract_allowed:
        invariants.append(
            InvariantSpec(
                id="input_contract_forbidden",
                description=(
                    f"Steps using the `{key}` input capability must not set "
                    "`input_contract`; the runtime rejects contract on "
                    "non-contract-allowed capabilities."
                ),
            )
        )
    if policy.requires_extraction:
        invariants.append(
            InvariantSpec(
                id="requires_non_empty_extraction",
                description=(
                    f"Steps using the `{key}` input capability must produce "
                    "non-empty extracted text at runtime; empty extraction "
                    "is rejected by `validate_runtime_input_policy`."
                ),
            )
        )
    if policy.requires_files:
        invariants.append(
            InvariantSpec(
                id="requires_at_least_one_file",
                description=(
                    f"Steps using the `{key}` input capability must present "
                    "at least one compatible file at runtime."
                ),
            )
        )
    return tuple(invariants)


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
        invariants=_absorbed_invariants(key, policy),
        exposure=exposure,
        not_exposed_reason=reason,
        channel=_narrow_channel(key, policy.channel),
        runtime_input_mode=_RUNTIME_INPUT_MODE_BY_KEY.get(key),
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


# Engine-truth mapping from output type to the artifact the runtime produces.
# Mirrors `BUILDER_FINAL_OUTPUT_ARTIFACT_BY_OUTPUT_TYPE` in
# `ai_builder/ai_builder_step_capabilities.py`; held in lockstep by a parity
# test until Phase G deletes the ai_builder copy. Covers every
# `FlowOutputType` — there is no runtime output type without an artifact.
FINAL_OUTPUT_ARTIFACT_BY_TYPE: Mapping[FlowOutputType, OutputArtifact] = (
    MappingProxyType(
        {
            FlowOutputType.TEXT: "structured_text",
            FlowOutputType.JSON: "structured_json",
            FlowOutputType.PDF: "pdf_document",
            FlowOutputType.DOCX: "docx_document",
        }
    )
)


def supports_step_io_tuple(
    *,
    input_type: FlowInputType | None,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> bool:
    """Engine-truth: is `(input_type, output_type, output_mode)` a legal
    combination at step level?

    Mirrors `supports_step_io_mode_combo` in
    `ai_builder/ai_builder_step_capabilities.py`; held in lockstep by a
    parity test until Phase G deletes the ai_builder copy. Rules:

    - `TEMPLATE_FILL` is legal only when `output_type` is `DOCX`.
    - `TRANSCRIBE_ONLY` is legal only for `AUDIO` input → `TEXT` output.
    - Every other combination is legal (the runtime pass-through default).

    `input_type` is optional because `TEMPLATE_FILL` and the pass-through
    default do not depend on it, so callers can answer output-mode legality
    before `input_type` has been decided. A `TRANSCRIBE_ONLY` query with
    `input_type=None` still returns `False` — transcription requires
    `AUDIO` input, never an unknown one.
    """
    if output_mode is FlowOutputMode.TEMPLATE_FILL:
        return output_type is FlowOutputType.DOCX
    if output_mode is FlowOutputMode.TRANSCRIBE_ONLY:
        return input_type is FlowInputType.AUDIO and output_type is FlowOutputType.TEXT
    return True


def resolve_document_generation_mode(
    *,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> DocumentGenerationMode | None:
    """Engine-truth: which document-generation pathway a `(output_type,
    output_mode)` pair triggers at runtime, if any.

    Mirrors `resolve_document_generation_mode` in
    `ai_builder/ai_builder_step_capabilities.py`; held in lockstep by a
    parity test until Phase G deletes the ai_builder copy.
    """
    if output_type is FlowOutputType.DOCX:
        return (
            "template_fill"
            if output_mode is FlowOutputMode.TEMPLATE_FILL
            else "generated"
        )
    if output_type is FlowOutputType.PDF:
        return "generated"
    return None


def is_citation_capable_step(
    *,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
    output_config: object,
) -> bool:
    """Engine-truth: can this step emit an inline-inref citation sidecar?

    Mirrors `is_citation_capable_step` in
    `ai_builder/ai_builder_step_capabilities.py`; held in lockstep by a
    parity test until Phase G deletes the ai_builder copy.

    Capability holds iff:
    - `output_config` is a dict that requests the
      `inline_inref_sidecar` citation mode, AND
    - `output_type` is `TEXT` (the only artefact the citation sidecar
      attaches to today), AND
    - `output_mode` is neither `TEMPLATE_FILL` nor `TRANSCRIBE_ONLY`
      (template-fill is a docx pathway; transcribe-only has no source
      documents to cite).

    `output_config` is typed as `object` rather than `dict` because
    `resolve_citation_mode` itself already tolerates any shape — a
    non-dict payload collapses to `off` and returns `False`. Keeping the
    wide type matches the legacy signature and covers malformed persisted
    payloads without the caller having to pre-validate.
    """
    if resolve_citation_mode(output_config) != CITATION_MODE_INLINE_INREF_SIDECAR:
        return False
    if output_type is not FlowOutputType.TEXT:
        return False
    return output_mode not in {
        FlowOutputMode.TEMPLATE_FILL,
        FlowOutputMode.TRANSCRIBE_ONLY,
    }
