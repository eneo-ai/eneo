"""Flow Capability Manifest (FCM) — engine truth about what is possible.

Declares the `FlowCapability` shape, seeds one entry per key in
`INPUT_TYPE_POLICIES`, absorbs chain-compatibility / citation /
transcription-wizard rules, and exposes the public API
(`resolve_capability_for_tuple`, `render_critic_invariants`,
`coverage_report`).

Engine-truth only: no Pattern Registry, no AI Builder, no planner prose.
Planner-facing copy and strategy live on the Pattern Registry and
Question Catalog.

Versioning discipline: `FCM_VERSION` is the monotonic integer stamped on
persisted plans, planning-state snapshots, and digests. Any
capability-surface change — new registry key, added/changed
`applies_to_tuples`, added/changed `FlowCapability` / nested-type field,
or altered `invariants` content — bumps the version and keeps any retired
capability resolvable with a deprecation reason for one bump cycle. The
bump-discipline CI test covers this full surface, not just keys and
`applies_to_tuples`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from eneo.flows.citation_sidecar import (
    CITATION_MODE_INLINE_INREF_SIDECAR,
    resolve_citation_mode,
)
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowMcpPolicy,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.type_policies import INPUT_TYPE_POLICIES, InputTypePolicy

FCM_VERSION: int = 2

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
    """Named config key this capability requires at runtime."""

    key: str


@dataclass(frozen=True)
class InvariantSpec:
    """Capability-semantic invariant — must hold whenever the capability is
    in use.
    """

    id: str
    description: str


@dataclass(frozen=True)
class FlowCapability:
    """Engine-truth capability entry.

    `applies_to_tuples`, `required_config`, and `invariants` declare the
    tuple legality, required config keys, and capability-semantic invariants
    that this capability carries.
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


# Engine-truth mapping from input type to the runtime input mode used by
# published flow execution. `IMAGE` and `ANY` are intentionally absent because
# the runtime has no input_mode for those input types.
RUNTIME_INPUT_MODE_BY_TYPE: Mapping[FlowInputType, RuntimeInputMode] = MappingProxyType(
    {
        FlowInputType.DOCUMENT: "documents",
        FlowInputType.FILE: "documents",
        FlowInputType.AUDIO: "audio",
        FlowInputType.TEXT: "text",
        FlowInputType.JSON: "text",
    }
)


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
    if key == "audio":
        invariants.append(
            InvariantSpec(
                id="requires_enabled_flow_transcription_config",
                description=(
                    "Flows containing any `AUDIO`-input step require "
                    "`metadata_json.wizard.transcription_enabled=True` and "
                    "a non-null `transcription_model.id`; "
                    "`_validate_audio_transcription_settings` rejects "
                    "missing config for every audio step regardless of "
                    "`output_mode`."
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
        runtime_input_mode=RUNTIME_INPUT_MODE_BY_TYPE.get(FlowInputType(key)),
    )


_OUTPUT_MODE_CAPABILITY_SEED: Mapping[
    FlowOutputMode, tuple[str, str, tuple[InvariantSpec, ...]]
] = MappingProxyType(
    {
        FlowOutputMode.PASS_THROUGH: (
            "Pass-through output",
            (
                "Default output pathway; the step's raw LLM output is forwarded "
                "to the next step or persisted as the flow's final artefact. "
                "No additional runtime constraints beyond the step chain."
            ),
            (),
        ),
        FlowOutputMode.HTTP_POST: (
            "HTTP POST output",
            (
                "Final output is delivered by POSTing to a configured URL. "
                "`output_config` must pass `validate_http_output_config`, "
                "which accepts the authored HTTP transport config. Concrete "
                "shape rules (URL, body, auth, timeout) live in the transport validators — this "
                "capability only asserts that a valid config exists."
            ),
            (
                InvariantSpec(
                    id="requires_http_output_config",
                    description=(
                        "Steps using `http_post` output mode must declare an "
                        "`output_config` object that passes "
                        "`validate_http_output_config`; the authored HTTP "
                        "transport config is the only accepted shape. The "
                        "capability does not pin per-field rules — see the "
                        "transport validators for URL scheme, body-mode, auth, "
                        "and timeout constraints."
                    ),
                ),
            ),
        ),
        FlowOutputMode.TRANSCRIBE_ONLY: (
            "Audio transcription (transcribe-only)",
            (
                "Non-LLM transcription pathway: audio input is transcribed to "
                "text by the flow's transcription backend. The step must be "
                "`AUDIO` input → `TEXT` output and, when runtime input is "
                "enabled, must declare `input_format='audio'`. The "
                "flow-level transcription-config rule is owned by the "
                "`input_audio` capability since it fires for every audio "
                "step, not only transcribe-only."
            ),
            (
                InvariantSpec(
                    id="requires_audio_input_text_output",
                    description=(
                        "Steps using `transcribe_only` must have `input_type="
                        "AUDIO` and `output_type=TEXT`; any other IO pair is "
                        "rejected by `supports_step_io_tuple`."
                    ),
                ),
                InvariantSpec(
                    id="requires_audio_runtime_input_format",
                    description=(
                        "Steps using `transcribe_only` with runtime_input "
                        "enabled must declare `input_format='audio'`; "
                        "`_validate_runtime_input_publish_rules` rejects "
                        "other formats."
                    ),
                ),
            ),
        ),
        FlowOutputMode.TEMPLATE_FILL: (
            "DOCX template fill",
            (
                "Final output is rendered by filling a DOCX template with "
                "step-scoped values. Constrained to DOCX output, incompatible "
                "with `output_contract`, and requires a concrete "
                "`template_fill` config block at publish time."
            ),
            (
                InvariantSpec(
                    id="requires_docx_output_type",
                    description=(
                        "Steps using `template_fill` must have "
                        "`output_type=DOCX`; `supports_step_io_tuple` rejects "
                        "other output types."
                    ),
                ),
                InvariantSpec(
                    id="forbids_output_contract",
                    description=(
                        "Steps using `template_fill` must not declare an "
                        "`output_contract`; "
                        "`_validate_output_contract_compatibility` raises when "
                        "the mode and contract coexist."
                    ),
                ),
                InvariantSpec(
                    id="requires_template_fill_output_config",
                    description=(
                        "Publishable flows with a `template_fill` step require "
                        "a complete `output_config` template block; "
                        "`validate_template_fill_output_config` enforces this "
                        "when `require_complete_template_fill_config=True`."
                    ),
                ),
            ),
        ),
    }
)


def _seed_output_mode_capability(mode: FlowOutputMode) -> FlowCapability:
    label, description, invariants = _OUTPUT_MODE_CAPABILITY_SEED[mode]
    return FlowCapability(
        id=f"output_mode_{mode.value}",
        label=label,
        description=description,
        applies_to_tuples=(),
        required_config=(),
        invariants=invariants,
        exposure="builder",
        not_exposed_reason=None,
    )


# Engine-truth allow-set for `step.mcp_policy`. Mirrors the legacy
# `_ALLOWED_FLOW_MCP_POLICIES` set at `flow_validators.py:57` (which is
# `set(FLOW_STEP_MCP_POLICY_VALUES)` — i.e. every enum value). The FCM
# copy is typed with the enum rather than strings so consumers can do
# enum-identity checks without re-parsing string values. Kept in lockstep
# with `FLOW_STEP_MCP_POLICY_VALUES` by a parity test.
ALLOWED_MCP_POLICIES: frozenset[FlowMcpPolicy] = frozenset(FlowMcpPolicy)


def _seed_mcp_policy_capability() -> FlowCapability:
    return FlowCapability(
        id="mcp_policy",
        label="MCP policy",
        description=(
            "Controls the flow step's MCP (Model Context Protocol) tool-access "
            "posture within the tenant → space → step cascade. Tenant admins "
            "enable MCP servers globally; space admins narrow that set per-MCP "
            "and per-tool within the space; the step then chooses which of the "
            "space-allowed MCPs/tools to expose at runtime. The legacy "
            "validator only enforces that `step.mcp_policy` is a known enum "
            "value; there are no per-value semantic rules today. If a future "
            "rule diverges per value (e.g. RESTRICTED gaining explicit runtime "
            "semantics), this singleton capability will split into per-value "
            "entries at that point."
        ),
        applies_to_tuples=(),
        required_config=(),
        invariants=(
            InvariantSpec(
                id="forbids_unsupported_mcp_policy",
                description=(
                    "Steps must declare `mcp_policy` as one of the values in "
                    "`ALLOWED_MCP_POLICIES` (i.e. every `FlowMcpPolicy` "
                    "member). `flow_validators.py:183` raises "
                    "`\"Step {order}: unsupported mcp_policy '{value}'.\"` "
                    "when the policy falls outside this set."
                ),
            ),
        ),
        exposure="builder",
        not_exposed_reason=None,
    )


def _seed_citation_sidecar_capability() -> FlowCapability:
    return FlowCapability(
        id="citation_sidecar",
        label="Inline-inref citation sidecar",
        description=(
            "Attaches an engine-managed citation sidecar to the step's TEXT "
            "output, tracking which context sources were cited via inline "
            "`[[inref:...]]` tags. Activated by `output_config.citation_mode="
            "'inline_inref_sidecar'`; compatible only with TEXT-output LLM "
            "steps that are not running in template-fill or transcribe-only "
            "mode."
        ),
        applies_to_tuples=(),
        required_config=(),
        invariants=(
            InvariantSpec(
                id="requires_text_output_type",
                description=(
                    "Citation capability holds only when `output_type=TEXT`; "
                    "`is_citation_capable_step` returns `False` for JSON/PDF/"
                    "DOCX outputs regardless of citation_mode."
                ),
            ),
            InvariantSpec(
                id="forbids_template_fill_or_transcribe_only",
                description=(
                    "Citation capability is disabled when `output_mode` is "
                    "`template_fill` (a docx-artefact pathway) or "
                    "`transcribe_only` (a non-LLM pathway). Any other "
                    "output_mode preserves capability when the rest holds."
                ),
            ),
            InvariantSpec(
                id="requires_citation_capable_output_config",
                description=(
                    "Citation capability requires "
                    "`resolve_citation_mode(output_config) == "
                    "'inline_inref_sidecar'`; any other resolved mode "
                    "(including `off`, missing keys, non-dict payloads) "
                    "collapses capability to `False`."
                ),
            ),
        ),
        exposure="builder",
        not_exposed_reason=None,
    )


CAPABILITY_REGISTRY: Mapping[CapabilityId, FlowCapability] = MappingProxyType(
    {
        **{
            f"input_{key}": _seed_input_type_capability(key, policy)
            for key, policy in INPUT_TYPE_POLICIES.items()
        },
        **{
            f"output_mode_{mode.value}": _seed_output_mode_capability(mode)
            for mode in FlowOutputMode
        },
        "mcp_policy": _seed_mcp_policy_capability(),
        "citation_sidecar": _seed_citation_sidecar_capability(),
    }
)


# Chain-composition truth: which `(previous_step_output_type, next_step_input_type)`
# pairs are legal when a step is fed by `input_source='previous_step'`. Only
# `previous_step` consults this table — `all_previous_steps` has its own rule
# path in `step_chain_rules.py` (the JSON-over-concatenated-text prohibition)
# and does not participate in type coercion. Mirrors
# `COMPATIBLE_TYPE_COERCIONS` from `step_chain_rules.py` as a typed FCM
# constant so consumers can read the rule without parsing the legacy
# string-tuple table. A parity test in `test_flow_capability_manifest.py`
# enforces lockstep.
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
# Covers every `FlowOutputType` — there is no runtime output type without an
# artifact.
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

    Strict enum-only contract: non-enum inputs raise `TypeError` rather
    than silently falling through the identity checks and returning the
    wrong answer. Callers that hold stringly-typed data must coerce at
    their boundary (typically `FlowOutputType(raw_string)`).

    Rules:

    - `TEMPLATE_FILL` is legal only when `output_type` is `DOCX`.
    - `TRANSCRIBE_ONLY` is legal only for `AUDIO` input → `TEXT` output.
    - Every other combination is legal (the runtime pass-through default).

    `input_type` is optional because `TEMPLATE_FILL` and the pass-through
    default do not depend on it, so callers can answer output-mode legality
    before `input_type` has been decided. A `TRANSCRIBE_ONLY` query with
    `input_type=None` still returns `False` — transcription requires
    `AUDIO` input, never an unknown one.
    """
    if input_type is not None and not isinstance(input_type, FlowInputType):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"input_type must be FlowInputType or None, got {type(input_type).__name__}"
        )
    if not isinstance(output_type, FlowOutputType):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"output_type must be FlowOutputType, got {type(output_type).__name__}"
        )
    if not isinstance(output_mode, FlowOutputMode):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"output_mode must be FlowOutputMode, got {type(output_mode).__name__}"
        )
    if output_mode is FlowOutputMode.TEMPLATE_FILL:
        return output_type is FlowOutputType.DOCX
    if output_mode is FlowOutputMode.TRANSCRIBE_ONLY:
        return input_type is FlowInputType.AUDIO and output_type is FlowOutputType.TEXT
    return True


def requires_completion_model(output_mode: FlowOutputMode) -> bool:
    """True when this output mode runs a completion model at runtime.

    Transcription-only steps route through the flow-scoped transcription
    configuration instead of an assistant completion model.
    """
    return output_mode is not FlowOutputMode.TRANSCRIBE_ONLY


def resolve_document_generation_mode(
    *,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> DocumentGenerationMode | None:
    """Engine-truth: which document-generation pathway a `(output_type,
    output_mode)` pair triggers at runtime, if any.

    Strict enum-only contract: non-enum inputs raise `TypeError` rather
    than silently returning `None` via failed identity checks.
    """
    if not isinstance(output_type, FlowOutputType):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"output_type must be FlowOutputType, got {type(output_type).__name__}"
        )
    if not isinstance(output_mode, FlowOutputMode):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"output_mode must be FlowOutputMode, got {type(output_mode).__name__}"
        )
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

    Strict enum-only contract for `output_type` and `output_mode`:
    non-enum inputs raise `TypeError` rather than silently returning
    `False` via a failed identity check.

    Capability holds iff:
    - `output_config` is a dict that requests the
      `inline_inref_sidecar` citation mode, AND
    - `output_type` is `TEXT` (the only artefact the citation sidecar
      attaches to today), AND
    - `output_mode` is neither `TEMPLATE_FILL` nor `TRANSCRIBE_ONLY`
      (template-fill is a docx pathway; transcribe-only has no source
      documents to cite).

    `output_config` stays typed as `object` because `resolve_citation_mode`
    itself already tolerates any shape — a non-dict payload collapses to
    `off` and returns `False`. Keeping the wide type covers malformed
    persisted payloads without the caller having to pre-validate.
    """
    if not isinstance(output_type, FlowOutputType):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"output_type must be FlowOutputType, got {type(output_type).__name__}"
        )
    if not isinstance(output_mode, FlowOutputMode):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"output_mode must be FlowOutputMode, got {type(output_mode).__name__}"
        )
    if resolve_citation_mode(output_config) != CITATION_MODE_INLINE_INREF_SIDECAR:
        return False
    if output_type is not FlowOutputType.TEXT:
        return False
    return output_mode not in {
        FlowOutputMode.TEMPLATE_FILL,
        FlowOutputMode.TRANSCRIBE_ONLY,
    }


# ---------------------------------------------------------------------
# Public API — capability resolution, invariant render, coverage report.
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageReport:
    """Summary of :func:`coverage_report`'s cartesian-product walk.

    Captures the four classification counts plus any cells whose owning
    `not_exposed_reason` contains the literal "temporary". The manifest
    forbids temporary exclusions — `has_drift=True` fails CI.
    """

    total_cells: int
    by_classification: Mapping[str, int]
    temporary_reasons: tuple[tuple[TupleSpec, str], ...]

    @property
    def has_drift(self) -> bool:
        return bool(self.temporary_reasons)


# Marker used by coverage_report to flag `not_exposed_reason` strings that
# advertise themselves as temporary. The manifest forbids such entries — they
# hide real coverage gaps behind a "we'll get back to it" escape hatch.
_TEMPORARY_REASON_MARKER = "temporary"


# Source-type legality rules mirrored from `step_chain_rules.py` and
# `flow_validators_http.py`. Single-cell in scope — step-order-dependent
# rules (e.g. step 1 cannot use `previous_step`) belong to
# `step_chain_rules.find_first_step_chain_violation`. `previous_step`
# chain-compat depends on the prior step's `output_type`; the single-cell
# `CHAIN_COMPATIBILITY` constant is guarded by its own parity test.
_HTTP_INPUT_SOURCES: frozenset[FlowInputSource] = frozenset(
    {FlowInputSource.HTTP_GET, FlowInputSource.HTTP_POST}
)
_FILE_INPUT_TYPES_BANNED_OVER_HTTP: frozenset[FlowInputType] = frozenset(
    {
        FlowInputType.DOCUMENT,
        FlowInputType.FILE,
        FlowInputType.IMAGE,
        FlowInputType.AUDIO,
    }
)
_FLOW_INPUT_ONLY_TYPES: frozenset[FlowInputType] = frozenset(
    {FlowInputType.DOCUMENT, FlowInputType.AUDIO, FlowInputType.FILE}
)


def _source_type_illegality(
    input_source: FlowInputSource, input_type: FlowInputType
) -> str | None:
    """Return a diagnostic string when `(input_source, input_type)` is
    illegal at the single-cell level, else `None`.

    Mirrors the three single-cell rules from `step_chain_rules.py` and
    `flow_validators_http.py`; the full set of chain-level rules lives in
    `step_chain_rules.find_first_step_chain_violation`.
    """
    if (
        input_source in _HTTP_INPUT_SOURCES
        and input_type in _FILE_INPUT_TYPES_BANNED_OVER_HTTP
    ):
        return (
            f"input_type {input_type.value!r} is not supported with "
            f"input_source {input_source.value!r} "
            "(flow_validators_http.validate_http_input_config)."
        )
    if (
        input_type in _FLOW_INPUT_ONLY_TYPES
        and input_source is not FlowInputSource.FLOW_INPUT
    ):
        return (
            f"input_type {input_type.value!r} only accepts input_source "
            "'flow_input' (step_chain_rules.find_first_step_chain_violation)."
        )
    if (
        input_type is FlowInputType.JSON
        and input_source is FlowInputSource.ALL_PREVIOUS_STEPS
    ):
        return (
            "input_type 'json' is incompatible with input_source "
            "'all_previous_steps' — concatenated text is not valid JSON."
        )
    return None


def _classify_cell(
    input_source: FlowInputSource,
    input_type: FlowInputType,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> tuple[str, str | None]:
    """Classify an FCM surface cell into one of four buckets.

    Returns ``(classification, diagnostic_or_reason)``. Classification is
    one of ``"illegal_io_triple"``, ``"illegal_source_type_pair"``,
    ``"not_exposed"``, ``"exposed"`` — every legal path terminates in one
    of those four.
    """
    if not supports_step_io_tuple(
        input_type=input_type, output_type=output_type, output_mode=output_mode
    ):
        return "illegal_io_triple", None
    source_type_issue = _source_type_illegality(input_source, input_type)
    if source_type_issue is not None:
        return "illegal_source_type_pair", source_type_issue
    input_cap = CAPABILITY_REGISTRY[f"input_{input_type.value}"]
    if input_cap.exposure == "not_exposed":
        return "not_exposed", input_cap.not_exposed_reason
    mode_cap = CAPABILITY_REGISTRY[f"output_mode_{output_mode.value}"]
    if mode_cap.exposure == "not_exposed":
        return "not_exposed", mode_cap.not_exposed_reason
    return "exposed", None


def resolve_capability_for_tuple(
    *,
    input_source: FlowInputSource,
    input_type: FlowInputType,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> tuple[FlowCapability, FlowCapability] | None:
    """Resolve owning capabilities for a legal step tuple, or None.

    Returns ``(input_capability, output_mode_capability)`` in that order
    for cells classified as ``"exposed"``. Returns ``None`` for
    illegal-IO-triple, illegal-source-type-pair, and not-exposed cells.

    Strict enum-only contract on all four axes — non-enum inputs raise
    `TypeError` at this public-API boundary so downstream helpers
    (`_classify_cell`, `_source_type_illegality`) can assume enums and
    their identity/membership checks cannot silently miss on stringly
    typed arguments. Callers that hold stringly-typed data must coerce
    at their own boundary (typically `FlowInputSource(raw_string)`).

    `citation_sidecar` and `mcp_policy` capabilities are intentionally
    NOT included — neither is conditioned on the 4-tuple alone.
    `render_critic_invariants` gives the flat "all invariants across all
    caps" view for the critic.
    """
    if not isinstance(input_source, FlowInputSource):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"input_source must be FlowInputSource, got {type(input_source).__name__}"
        )
    if not isinstance(input_type, FlowInputType):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"input_type must be FlowInputType, got {type(input_type).__name__}"
        )
    if not isinstance(output_type, FlowOutputType):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"output_type must be FlowOutputType, got {type(output_type).__name__}"
        )
    if not isinstance(output_mode, FlowOutputMode):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"output_mode must be FlowOutputMode, got {type(output_mode).__name__}"
        )
    classification, _reason = _classify_cell(
        input_source, input_type, output_type, output_mode
    )
    if classification != "exposed":
        return None
    input_cap = CAPABILITY_REGISTRY[f"input_{input_type.value}"]
    mode_cap = CAPABILITY_REGISTRY[f"output_mode_{output_mode.value}"]
    return (input_cap, mode_cap)


def render_critic_invariants() -> tuple[tuple[CapabilityId, InvariantSpec], ...]:
    """Flat view of every capability-owned invariant, for the critic.

    Each entry is ``(capability_id, invariant)``. Ownership is returned
    explicitly because invariant IDs are not globally unique — e.g.
    `input_contract_forbidden` is emitted by every input capability that
    disallows contracts, and `requires_non_empty_extraction` by every
    capability that requires extraction. Consumers need the owning
    capability ID to disambiguate.

    Order: sorted by `(capability_id, invariant.id)` ascending so
    consumer iteration is deterministic across process restarts and
    across capability additions.
    """
    result: list[tuple[CapabilityId, InvariantSpec]] = []
    for cap_id in sorted(CAPABILITY_REGISTRY):
        cap = CAPABILITY_REGISTRY[cap_id]
        for inv in sorted(cap.invariants, key=lambda i: i.id):
            result.append((cap_id, inv))
    return tuple(result)


def coverage_report() -> CoverageReport:
    """Walk the cartesian product of the four enums and summarize coverage.

    Used by the cell-classification test and by dev-time diagnostics. Every
    cell lands in exactly one of four buckets; a cell whose owning
    `not_exposed_reason` contains the literal ``"temporary"`` surfaces in
    ``temporary_reasons`` and flips ``has_drift`` to ``True``.
    """
    counts: dict[str, int] = {
        "exposed": 0,
        "illegal_io_triple": 0,
        "illegal_source_type_pair": 0,
        "not_exposed": 0,
    }
    temporary: list[tuple[TupleSpec, str]] = []
    total = 0
    for input_source in FlowInputSource:
        for input_type in FlowInputType:
            for output_type in FlowOutputType:
                for output_mode in FlowOutputMode:
                    total += 1
                    classification, reason = _classify_cell(
                        input_source, input_type, output_type, output_mode
                    )
                    counts[classification] += 1
                    if (
                        classification == "not_exposed"
                        and reason is not None
                        and _TEMPORARY_REASON_MARKER in reason
                    ):
                        temporary.append(
                            (
                                (input_source, input_type, output_type, output_mode),
                                reason,
                            )
                        )
    return CoverageReport(
        total_cells=total,
        by_classification=MappingProxyType(counts),
        temporary_reasons=tuple(temporary),
    )
