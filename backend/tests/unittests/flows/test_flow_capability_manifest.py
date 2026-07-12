"""Flow Capability Manifest tests.

Covers: version constant, dataclass shape (engine-truth fields only),
registry seeding from `INPUT_TYPE_POLICIES`, `not_exposed_reason`
invariant, tuple-matrix coverage guard, FCM_VERSION bump-discipline, and
the public API (`resolve_capability_for_tuple`, `coverage_report`).
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_form_field_type_values,
)
from eneo.flows.citation_sidecar import CITATION_MODE_INLINE_INREF_SIDECAR
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_authoring_spec import _VALID_FORM_FIELD_TYPES
from eneo.flows.flow_capability_manifest import (
    _TEMPORARY_REASON_MARKER,
    CAPABILITY_REGISTRY,
    CHAIN_COMPATIBILITY,
    FCM_VERSION,
    FINAL_OUTPUT_ARTIFACT_BY_TYPE,
    RUNTIME_INPUT_MODE_BY_TYPE,
    ConfigRequirement,
    CoverageReport,
    FlowCapability,
    InvariantSpec,
    _classify_cell,
    coverage_report,
    is_chain_compatible,
    is_citation_capable_step,
    requires_completion_model,
    resolve_capability_for_tuple,
    resolve_document_generation_mode,
    supports_step_io_tuple,
)
from eneo.flows.type_policies import INPUT_TYPE_POLICIES


def _flow_capability_manifest_source() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "src"
        / "eneo"
        / "flows"
        / "flow_capability_manifest.py"
    )


def test_fcm_version_is_seven() -> None:
    assert FCM_VERSION == 7


def test_ai_builder_form_field_types_match_flow_authoring_values() -> None:
    assert set(builder_form_field_type_values()) == _VALID_FORM_FIELD_TYPES


def test_flow_capability_is_frozen_with_engine_truth_fields() -> None:
    capability = FlowCapability(
        id="fixture",
        label="fixture",
        description="fixture",
        applies_to_tuples=(),
        required_config=(),
        invariants=(),
        exposure="builder",
        not_exposed_reason=None,
    )
    assert capability.id == "fixture"
    assert capability.exposure == "builder"
    assert capability.applies_to_tuples == ()
    with pytest.raises(FrozenInstanceError):
        capability.id = "mutated"  # type: ignore[misc]


def test_registry_has_one_entry_per_input_type_policy() -> None:
    seeded_ids = {
        cap.id for cap in CAPABILITY_REGISTRY.values() if cap.id.startswith("input_")
    }
    expected_ids = {f"input_{key}" for key in INPUT_TYPE_POLICIES}
    assert seeded_ids == expected_ids


@pytest.mark.parametrize("input_key", sorted(INPUT_TYPE_POLICIES.keys()))
def test_registry_exposure_tracks_policy_supported_flag(input_key: str) -> None:
    policy = INPUT_TYPE_POLICIES[input_key]
    capability = CAPABILITY_REGISTRY[f"input_{input_key}"]
    if policy.supported:
        assert capability.exposure == "builder"
        assert capability.not_exposed_reason is None
    else:
        assert capability.exposure == "not_exposed"
        assert capability.not_exposed_reason is not None
        assert capability.not_exposed_reason.strip() != ""


def test_not_exposed_capability_requires_reason() -> None:
    with pytest.raises(ValueError, match="not_exposed_reason"):
        FlowCapability(
            id="fixture",
            label="fixture",
            description="fixture",
            applies_to_tuples=(),
            required_config=(),
            invariants=(),
            exposure="not_exposed",
            not_exposed_reason=None,
        )


def test_engine_only_capability_requires_reason() -> None:
    with pytest.raises(ValueError, match="not_exposed_reason"):
        FlowCapability(
            id="fixture",
            label="fixture",
            description="fixture",
            applies_to_tuples=(),
            required_config=(),
            invariants=(),
            exposure="engine_only",
            not_exposed_reason=None,
        )


def test_engine_only_capability_accepts_valid_reason() -> None:
    """Positive path: `engine_only` with a non-empty reason is constructible.
    Guards against future regressions where the symmetric invariant starts
    rejecting valid states by mistake."""
    capability = FlowCapability(
        id="engine_only_fixture",
        label="fixture",
        description="fixture",
        applies_to_tuples=(),
        required_config=(),
        invariants=(),
        exposure="engine_only",
        not_exposed_reason="Engine-internal plumbing; no builder surface.",
    )
    assert capability.exposure == "engine_only"
    assert capability.not_exposed_reason is not None


def test_builder_exposure_rejects_spurious_reason() -> None:
    """Engine-truth cannot admit contradictory state. A builder-exposed
    capability cannot carry a `not_exposed_reason`."""
    with pytest.raises(ValueError, match="not_exposed_reason"):
        FlowCapability(
            id="fixture",
            label="fixture",
            description="fixture",
            applies_to_tuples=(),
            required_config=(),
            invariants=(),
            exposure="builder",
            not_exposed_reason="spurious reason that should be rejected",
        )


def test_capability_registry_is_immutable() -> None:
    """`CAPABILITY_REGISTRY` is a `MappingProxyType`; mutation at runtime
    must fail. The manifest is canonical — consumers must not patch it."""
    from eneo.flows.flow_capability_manifest import CAPABILITY_REGISTRY

    with pytest.raises(TypeError):
        CAPABILITY_REGISTRY["input_new"] = CAPABILITY_REGISTRY["input_text"]  # type: ignore[index]
    with pytest.raises(TypeError):
        del CAPABILITY_REGISTRY["input_text"]  # type: ignore[misc]


def test_chain_compatibility_is_frozen_and_typed_with_enums() -> None:
    """`CHAIN_COMPATIBILITY` must be a frozenset of
    `(FlowOutputType, FlowInputType)` pairs — i.e. typed, not bare strings."""
    assert isinstance(CHAIN_COMPATIBILITY, frozenset)
    for pair in CHAIN_COMPATIBILITY:
        assert isinstance(pair, tuple) and len(pair) == 2
        out_type, in_type = pair
        assert isinstance(out_type, FlowOutputType), (
            f"CHAIN_COMPATIBILITY key {pair!r} — out-type must be a FlowOutputType"
        )
        assert isinstance(in_type, FlowInputType), (
            f"CHAIN_COMPATIBILITY key {pair!r} — in-type must be a FlowInputType"
        )


def test_chain_compatibility_predicate_uses_typed_fcm_truth() -> None:
    assert is_chain_compatible(
        output_type=FlowOutputType.TEXT,
        input_type=FlowInputType.JSON,
    )
    assert not is_chain_compatible(
        output_type=FlowOutputType.DOCX,
        input_type=FlowInputType.JSON,
    )


def test_chain_compatibility_predicate_rejects_non_enum_values() -> None:
    with pytest.raises(TypeError, match="output_type must be FlowOutputType"):
        is_chain_compatible(
            output_type="text",  # type: ignore[arg-type]
            input_type=FlowInputType.JSON,
        )
    with pytest.raises(TypeError, match="input_type must be FlowInputType"):
        is_chain_compatible(
            output_type=FlowOutputType.TEXT,
            input_type="json",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("input_key", sorted(INPUT_TYPE_POLICIES.keys()))
def test_capability_channel_mirrors_policy(input_key: str) -> None:
    """Every seeded input capability carries the same `channel` as its
    `InputTypePolicy`. FCM is the typed mirror; `type_policies.py` remains
    the editable source."""
    policy = INPUT_TYPE_POLICIES[input_key]
    capability = CAPABILITY_REGISTRY[f"input_{input_key}"]
    assert capability.channel == policy.channel


@pytest.mark.parametrize("input_key", sorted(INPUT_TYPE_POLICIES.keys()))
def test_capability_invariants_track_policy_flags(input_key: str) -> None:
    """Each of the three policy-derived invariants is present iff the
    corresponding flag on `InputTypePolicy` demands it. Drift between
    seeder and policy is caught here."""
    policy = INPUT_TYPE_POLICIES[input_key]
    capability = CAPABILITY_REGISTRY[f"input_{input_key}"]
    invariant_ids = {inv.id for inv in capability.invariants}
    assert ("input_contract_forbidden" in invariant_ids) == (
        not policy.contract_allowed
    )
    assert ("requires_non_empty_extraction" in invariant_ids) == (
        policy.requires_extraction
    )
    assert ("requires_at_least_one_file" in invariant_ids) == policy.requires_files


def test_input_capability_rejects_missing_channel() -> None:
    """Every `input_*` capability must declare a channel. `channel=None`
    is valid for non-input capabilities (citation, transcription wizard,
    MCP) but never for an input capability — the runtime uses `channel`
    to decide whether to forward file bytes to the LLM."""
    with pytest.raises(ValueError, match="channel"):
        FlowCapability(
            id="input_fixture",
            label="fixture",
            description="fixture",
            applies_to_tuples=(),
            required_config=(),
            invariants=(),
            exposure="builder",
            not_exposed_reason=None,
            channel=None,
        )


@pytest.mark.parametrize(
    "output_mode",
    list(FlowOutputMode),
)
def test_requires_completion_model_rejects_transcribe_only(
    output_mode: FlowOutputMode,
) -> None:
    expected = output_mode not in {
        FlowOutputMode.COMPOSE_TEXT,
        FlowOutputMode.TRANSCRIBE_ONLY,
        FlowOutputMode.RENDER_VERBATIM,
    }

    assert requires_completion_model(output_mode) is expected


def test_input_text_has_no_absorbed_invariants() -> None:
    """Positive guardrail: `input_text` has `contract_allowed=True`,
    `requires_extraction=False`, `requires_files=False` → zero absorbed
    invariants. Catches a future seeder bug that would add spurious
    invariants where the policy has none."""
    capability = CAPABILITY_REGISTRY["input_text"]
    assert capability.invariants == ()
    assert capability.channel == "text_only"


_EXPECTED_RUNTIME_INPUT_MODE_BY_TYPE = {
    FlowInputType.DOCUMENT: "documents",
    FlowInputType.FILE: "documents",
    FlowInputType.AUDIO: "audio",
    FlowInputType.TEXT: "text",
    FlowInputType.JSON: "text",
}


def test_runtime_input_mode_by_type_is_fcm_owned_and_typed() -> None:
    assert RUNTIME_INPUT_MODE_BY_TYPE == _EXPECTED_RUNTIME_INPUT_MODE_BY_TYPE
    assert FlowInputType.IMAGE not in RUNTIME_INPUT_MODE_BY_TYPE
    assert FlowInputType.ANY not in RUNTIME_INPUT_MODE_BY_TYPE
    for input_type in RUNTIME_INPUT_MODE_BY_TYPE:
        assert isinstance(input_type, FlowInputType), (
            f"RUNTIME_INPUT_MODE_BY_TYPE key {input_type!r} must be a "
            "FlowInputType enum, not a bare string."
        )
    with pytest.raises(TypeError):
        RUNTIME_INPUT_MODE_BY_TYPE[FlowInputType.TEXT] = "mutated"  # type: ignore[index]


@pytest.mark.parametrize("input_type", list(FlowInputType))
def test_capability_runtime_input_mode_uses_fcm_mapping(
    input_type: FlowInputType,
) -> None:
    """Seeded `input_*` capabilities carry the FCM-owned runtime-input
    mode. `image` and `any` intentionally carry `None` because the runtime
    has no input_mode for those input types."""
    capability = CAPABILITY_REGISTRY[f"input_{input_type.value}"]
    expected = RUNTIME_INPUT_MODE_BY_TYPE.get(input_type)
    assert capability.runtime_input_mode == expected


def test_final_output_artifact_by_type_is_fcm_owned() -> None:
    assert FINAL_OUTPUT_ARTIFACT_BY_TYPE == {
        FlowOutputType.TEXT: "structured_text",
        FlowOutputType.JSON: "structured_json",
        FlowOutputType.PDF: "pdf_document",
        FlowOutputType.DOCX: "docx_document",
    }


def test_final_output_artifact_by_type_is_frozen_and_typed_with_enums() -> None:
    """The FCM mirror must be an immutable `Mapping` keyed by
    `FlowOutputType` enums — consumers rely on typed dispatch, not string
    lookups. Also covers every enum member so no output type is orphaned."""
    assert set(FINAL_OUTPUT_ARTIFACT_BY_TYPE.keys()) == set(FlowOutputType)
    for out_type in FINAL_OUTPUT_ARTIFACT_BY_TYPE:
        assert isinstance(out_type, FlowOutputType), (
            f"FINAL_OUTPUT_ARTIFACT_BY_TYPE key {out_type!r} must be a "
            "FlowOutputType enum, not a bare string."
        )
    with pytest.raises(TypeError):
        FINAL_OUTPUT_ARTIFACT_BY_TYPE[FlowOutputType.TEXT] = "mutated"  # type: ignore[index]


def test_resolve_document_generation_mode_maps_document_outputs() -> None:
    assert (
        resolve_document_generation_mode(
            output_type=FlowOutputType.DOCX,
            output_mode=FlowOutputMode.TEMPLATE_FILL,
        )
        == "template_fill"
    )
    assert (
        resolve_document_generation_mode(
            output_type=FlowOutputType.DOCX,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )
        == "generated"
    )
    assert (
        resolve_document_generation_mode(
            output_type=FlowOutputType.PDF,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )
        == "generated"
    )
    assert (
        resolve_document_generation_mode(
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )
        is None
    )
    assert (
        resolve_document_generation_mode(
            output_type=FlowOutputType.JSON,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )
        is None
    )


def test_supports_step_io_tuple_rejects_template_fill_for_non_docx() -> None:
    """Explicit rule guardrail (not just parity): template_fill is only legal
    when output_type is docx. Catches a regression that silently drops the
    restriction."""
    for output_type in FlowOutputType:
        legal = supports_step_io_tuple(
            input_type=FlowInputType.TEXT,
            output_type=output_type,
            output_mode=FlowOutputMode.TEMPLATE_FILL,
        )
        assert legal is (output_type is FlowOutputType.DOCX)


def test_supports_step_io_tuple_rejects_transcribe_only_for_non_audio_text() -> None:
    """Explicit rule guardrail: transcribe_only is only legal for
    audio-in → text-out. Any other combination must be rejected."""
    for input_type in FlowInputType:
        for output_type in FlowOutputType:
            legal = supports_step_io_tuple(
                input_type=input_type,
                output_type=output_type,
                output_mode=FlowOutputMode.TRANSCRIBE_ONLY,
            )
            expected = (
                input_type is FlowInputType.AUDIO and output_type is FlowOutputType.TEXT
            )
            assert legal is expected


def test_supports_step_io_tuple_rejects_compose_text_for_non_text_text() -> None:
    for input_type in FlowInputType:
        for output_type in FlowOutputType:
            legal = supports_step_io_tuple(
                input_type=input_type,
                output_type=output_type,
                output_mode=FlowOutputMode.COMPOSE_TEXT,
            )
            expected = (
                input_type is FlowInputType.TEXT and output_type is FlowOutputType.TEXT
            )
            assert legal is expected


def test_supports_step_io_tuple_rejects_render_verbatim_for_non_text_document() -> None:
    for input_type in FlowInputType:
        for output_type in FlowOutputType:
            legal = supports_step_io_tuple(
                input_type=input_type,
                output_type=output_type,
                output_mode=FlowOutputMode.RENDER_VERBATIM,
            )
            expected = input_type is FlowInputType.TEXT and output_type in {
                FlowOutputType.PDF,
                FlowOutputType.DOCX,
            }
            assert legal is expected


def test_supports_step_io_tuple_rejects_text_document_pass_through() -> None:
    for output_type in (FlowOutputType.PDF, FlowOutputType.DOCX):
        assert (
            supports_step_io_tuple(
                input_type=FlowInputType.TEXT,
                output_type=output_type,
                output_mode=FlowOutputMode.PASS_THROUGH,
            )
            is False
        )
        assert (
            supports_step_io_tuple(
                input_type=FlowInputType.JSON,
                output_type=output_type,
                output_mode=FlowOutputMode.PASS_THROUGH,
            )
            is True
        )


def test_is_citation_capable_step_requires_inline_inref_sidecar_mode() -> None:
    """Explicit rule guardrail: only `inline_inref_sidecar` citation mode
    unlocks citation capability. Any other recognisable mode (including the
    explicit 'off' sentinel and an unknown mode string) must return False
    even when the rest of the step is citation-friendly."""
    assert (
        is_citation_capable_step(
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.PASS_THROUGH,
            output_config={"citation_mode": "  inline_inref_sidecar  "},
        )
        is True
    )
    for bad_mode in ("off", "unknown_mode", "", "inline", "sidecar"):
        assert (
            is_citation_capable_step(
                output_type=FlowOutputType.TEXT,
                output_mode=FlowOutputMode.PASS_THROUGH,
                output_config={"citation_mode": bad_mode},
            )
            is False
        ), f"non-sidecar citation_mode={bad_mode!r} must not unlock capability"
    assert (
        is_citation_capable_step(
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.PASS_THROUGH,
            output_config={"citation_mode": 1},
        )
        is False
    )


def test_is_citation_capable_step_requires_text_output() -> None:
    """Explicit rule guardrail: citation capability is TEXT-output only, even
    when the sidecar is enabled. JSON/PDF/DOCX outputs must all reject
    capability — the engine does not support inline-inref sidecars on
    non-text outputs."""
    enabled_config = {"citation_mode": CITATION_MODE_INLINE_INREF_SIDECAR}
    for output_type in FlowOutputType:
        result = is_citation_capable_step(
            output_type=output_type,
            output_mode=FlowOutputMode.PASS_THROUGH,
            output_config=enabled_config,
        )
        assert result is (output_type is FlowOutputType.TEXT), (
            f"citation capability must be TEXT-only; got {result} for {output_type}"
        )


def test_is_citation_capable_step_rejects_template_fill_and_transcribe_only() -> None:
    """Explicit rule guardrail: even on TEXT output with sidecar enabled, the
    `TEMPLATE_FILL`, `TRANSCRIBE_ONLY`, and `RENDER_VERBATIM` output modes
    must reject citation capability — none of them produces a citation-aware
    LLM text response."""
    enabled_config = {"citation_mode": CITATION_MODE_INLINE_INREF_SIDECAR}
    for output_mode in FlowOutputMode:
        result = is_citation_capable_step(
            output_type=FlowOutputType.TEXT,
            output_mode=output_mode,
            output_config=enabled_config,
        )
        expected = output_mode not in {
            FlowOutputMode.COMPOSE_TEXT,
            FlowOutputMode.TEMPLATE_FILL,
            FlowOutputMode.TRANSCRIBE_ONLY,
            FlowOutputMode.RENDER_VERBATIM,
        }
        assert result is expected, (
            f"citation capability for TEXT + {output_mode} must be {expected}; got {result}"
        )


@pytest.mark.parametrize(
    "non_dict_config",
    [None, "not a dict", 42, 0, 1.5, True, False, [], (), ["citation_mode"]],
)
def test_is_citation_capable_step_treats_non_dict_config_as_off(
    non_dict_config: object,
) -> None:
    """Regression guardrail: `resolve_citation_mode` returns `off` for any
    non-dict `output_config`. Citation capability must therefore be False for
    all non-dict inputs, independent of the step's output_type/mode. Matches
    the legacy runtime defence-in-depth against malformed config payloads."""
    assert (
        is_citation_capable_step(
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.PASS_THROUGH,
            output_config=non_dict_config,
        )
        is False
    )


def test_supports_step_io_tuple_rejects_string_output_mode() -> None:
    """The strict enum-only contract must reject stringly-typed callers
    loudly. A silent fall-through to `return True` on a non-enum
    `output_mode` would let `(input_type='text', output_type='pdf',
    output_mode='template_fill')` pretend to be legal."""
    with pytest.raises(TypeError, match="output_mode must be FlowOutputMode"):
        supports_step_io_tuple(
            input_type=FlowInputType.TEXT,
            output_type=FlowOutputType.PDF,
            output_mode="template_fill",  # type: ignore[arg-type]
        )


def test_supports_step_io_tuple_rejects_string_output_type() -> None:
    with pytest.raises(TypeError, match="output_type must be FlowOutputType"):
        supports_step_io_tuple(
            input_type=FlowInputType.TEXT,
            output_type="pdf",  # type: ignore[arg-type]
            output_mode=FlowOutputMode.PASS_THROUGH,
        )


def test_supports_step_io_tuple_rejects_string_input_type() -> None:
    with pytest.raises(TypeError, match="input_type must be FlowInputType"):
        supports_step_io_tuple(
            input_type="audio",  # type: ignore[arg-type]
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.TRANSCRIBE_ONLY,
        )


def test_supports_step_io_tuple_accepts_none_input_type() -> None:
    assert (
        supports_step_io_tuple(
            input_type=None,
            output_type=FlowOutputType.DOCX,
            output_mode=FlowOutputMode.TEMPLATE_FILL,
        )
        is True
    )


def test_resolve_document_generation_mode_rejects_string_output_type() -> None:
    with pytest.raises(TypeError, match="output_type must be FlowOutputType"):
        resolve_document_generation_mode(
            output_type="docx",  # type: ignore[arg-type]
            output_mode=FlowOutputMode.TEMPLATE_FILL,
        )


def test_resolve_document_generation_mode_rejects_string_output_mode() -> None:
    with pytest.raises(TypeError, match="output_mode must be FlowOutputMode"):
        resolve_document_generation_mode(
            output_type=FlowOutputType.DOCX,
            output_mode="template_fill",  # type: ignore[arg-type]
        )


def test_is_citation_capable_step_rejects_string_output_type() -> None:
    with pytest.raises(TypeError, match="output_type must be FlowOutputType"):
        is_citation_capable_step(
            output_type="text",  # type: ignore[arg-type]
            output_mode=FlowOutputMode.PASS_THROUGH,
            output_config={"citation_mode": "inline_inref_sidecar"},
        )


def test_is_citation_capable_step_rejects_string_output_mode() -> None:
    with pytest.raises(TypeError, match="output_mode must be FlowOutputMode"):
        is_citation_capable_step(
            output_type=FlowOutputType.TEXT,
            output_mode="pass_through",  # type: ignore[arg-type]
            output_config={"citation_mode": "inline_inref_sidecar"},
        )


def test_resolve_capability_for_tuple_rejects_string_input_source() -> None:
    """`resolve_capability_for_tuple` is the public-API boundary for the
    strict enum contract. A stringly-typed `input_source` would slip past
    `_source_type_illegality`'s identity/membership checks and silently
    classify as `"exposed"`, returning capabilities that do not reflect
    the invalid source. The runtime guard raises instead."""
    with pytest.raises(TypeError, match="input_source must be FlowInputSource"):
        resolve_capability_for_tuple(
            input_source="http",  # type: ignore[arg-type]
            input_type=FlowInputType.TEXT,
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )


def test_resolve_capability_for_tuple_rejects_string_input_type() -> None:
    with pytest.raises(TypeError, match="input_type must be FlowInputType"):
        resolve_capability_for_tuple(
            input_source=FlowInputSource.FLOW_INPUT,
            input_type="text",  # type: ignore[arg-type]
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )


def test_resolve_capability_for_tuple_rejects_string_output_type() -> None:
    with pytest.raises(TypeError, match="output_type must be FlowOutputType"):
        resolve_capability_for_tuple(
            input_source=FlowInputSource.FLOW_INPUT,
            input_type=FlowInputType.TEXT,
            output_type="text",  # type: ignore[arg-type]
            output_mode=FlowOutputMode.PASS_THROUGH,
        )


def test_resolve_capability_for_tuple_rejects_string_output_mode() -> None:
    with pytest.raises(TypeError, match="output_mode must be FlowOutputMode"):
        resolve_capability_for_tuple(
            input_source=FlowInputSource.FLOW_INPUT,
            input_type=FlowInputType.TEXT,
            output_type=FlowOutputType.TEXT,
            output_mode="pass_through",  # type: ignore[arg-type]
        )


# Output-mode + citation capability registry entries --------------------
#
# These tests pin the capability IDs and invariant-ID sets that FCM must
# declare for each `FlowOutputMode` + the citation sidecar. The invariant
# IDs are grep-matched against the legacy error phrases in
# `flow_validators.py:validate_steps`, so consumers applying invariants by
# capability ownership know which capability carries each rule.


_EXPECTED_OUTPUT_MODE_CAPABILITIES: dict[FlowOutputMode, tuple[str, frozenset[str]]] = {
    FlowOutputMode.PASS_THROUGH: (
        "output_mode_pass_through",
        frozenset({"forbids_text_document_render_path"}),
    ),
    FlowOutputMode.HTTP_POST: (
        "output_mode_http_post",
        frozenset({"requires_http_output_config"}),
    ),
    FlowOutputMode.COMPOSE_TEXT: (
        "output_mode_compose_text",
        frozenset({"requires_text_input_text_output"}),
    ),
    FlowOutputMode.TRANSCRIBE_ONLY: (
        "output_mode_transcribe_only",
        frozenset(
            {
                "requires_audio_input_text_output",
                "requires_audio_runtime_input_format",
            }
        ),
    ),
    FlowOutputMode.TEMPLATE_FILL: (
        "output_mode_template_fill",
        frozenset(
            {
                "requires_docx_output_type",
                "forbids_output_contract",
                "requires_template_fill_output_config",
            }
        ),
    ),
    FlowOutputMode.RENDER_VERBATIM: (
        "output_mode_render_verbatim",
        frozenset({"requires_text_input_document_output", "forbids_output_contract"}),
    ),
}


@pytest.mark.parametrize(
    "output_mode,expected",
    list(_EXPECTED_OUTPUT_MODE_CAPABILITIES.items()),
    ids=[mode.value for mode in _EXPECTED_OUTPUT_MODE_CAPABILITIES],
)
def test_registry_has_output_mode_capability(
    output_mode: FlowOutputMode, expected: tuple[str, frozenset[str]]
) -> None:
    """Every `FlowOutputMode` must have a capability entry whose `id`
    matches the `output_mode_<value>` convention and whose invariant IDs
    match the lifted rule set from `flow_validators.py:66`."""
    capability_id, expected_invariant_ids = expected
    capability = CAPABILITY_REGISTRY.get(capability_id)
    assert capability is not None, (
        f"CAPABILITY_REGISTRY missing entry for {output_mode} — "
        f"expected id {capability_id!r}"
    )
    assert capability.exposure == "builder", (
        f"{capability_id} must be exposure='builder' — output modes are "
        "user-facing via the flow publish API"
    )
    invariant_ids = frozenset(inv.id for inv in capability.invariants)
    assert invariant_ids == expected_invariant_ids, (
        f"{capability_id} invariant drift: expected {expected_invariant_ids}, "
        f"got {invariant_ids}"
    )


def test_registry_has_citation_sidecar_capability() -> None:
    """Citation capability must be a first-class registry entry carrying
    the three lifted invariants from the legacy `is_citation_capable_step`
    predicate + `_validate_citation_mode` validator: TEXT output required,
    TEMPLATE_FILL / TRANSCRIBE_ONLY forbidden, and the output_config must
    be citation-capable. Distinct from the `is_citation_capable_step` FCM
    function, which is a step-level predicate."""
    capability = CAPABILITY_REGISTRY.get("citation_sidecar")
    assert capability is not None, "citation_sidecar capability missing"
    assert capability.exposure == "builder", (
        "citation_sidecar is builder-addressable via output_config.citation_mode"
    )
    expected_invariant_ids = frozenset(
        {
            "requires_text_output_type",
            "forbids_template_fill_or_transcribe_only",
            "requires_citation_capable_output_config",
        }
    )
    invariant_ids = frozenset(inv.id for inv in capability.invariants)
    assert invariant_ids == expected_invariant_ids, (
        f"citation_sidecar invariant drift: expected {expected_invariant_ids}, "
        f"got {invariant_ids}"
    )


def test_input_audio_owns_transcription_config_invariant() -> None:
    """`_validate_audio_transcription_settings` fires for every audio-input
    step, not just transcribe-only ones (see `flow_validators.py:261` — the
    guard is `any(step.input_type == "audio" ...)`), so the
    `requires_enabled_flow_transcription_config` invariant belongs on the
    `input_audio` capability. Consumers applying invariants by capability
    ownership must reject pass-through audio steps with disabled
    transcription just like transcribe-only ones."""
    capability = CAPABILITY_REGISTRY["input_audio"]
    invariant_ids = {inv.id for inv in capability.invariants}
    assert "requires_enabled_flow_transcription_config" in invariant_ids, (
        "input_audio must carry the transcription-config invariant — the "
        "legacy rule fires for every audio step regardless of output_mode"
    )

    transcribe_ids = {
        inv.id for inv in CAPABILITY_REGISTRY["output_mode_transcribe_only"].invariants
    }
    assert "requires_enabled_flow_transcription_config" not in transcribe_ids, (
        "requires_enabled_flow_transcription_config must NOT be on "
        "output_mode_transcribe_only; pass-through audio steps would lose "
        "the rule under capability-ownership lookup"
    )


def test_registry_output_mode_coverage_is_exhaustive() -> None:
    """Every `FlowOutputMode` value must appear in the registry with an
    `output_mode_<value>` key. Catches a future enum addition that forgets
    to register a capability entry."""
    registered_ids = {
        cap.id
        for cap in CAPABILITY_REGISTRY.values()
        if cap.id.startswith("output_mode_")
    }
    expected_ids = {f"output_mode_{mode.value}" for mode in FlowOutputMode}
    assert registered_ids == expected_ids, (
        f"output_mode coverage drift: missing {expected_ids - registered_ids}, "
        f"extra {registered_ids - expected_ids}"
    )


def test_output_mode_and_citation_capabilities_are_non_input() -> None:
    """Output-mode + citation capabilities are not input capabilities, so
    they must carry `channel=None` and `runtime_input_mode=None` — the
    `input_*` post_init guard does not apply to them."""
    non_input_ids = {
        cap.id
        for cap in CAPABILITY_REGISTRY.values()
        if not cap.id.startswith("input_")
    }
    assert non_input_ids  # sanity: non-input capability entries exist
    for cap_id in non_input_ids:
        capability = CAPABILITY_REGISTRY[cap_id]
        assert capability.channel is None, (
            f"{cap_id} is not an input capability; channel must be None"
        )
        assert capability.runtime_input_mode is None, (
            f"{cap_id} is not an input capability; runtime_input_mode must be None"
        )


def test_fcm_module_has_no_ai_builder_imports() -> None:
    """Redundant with the `importlinter` contract but keeps the invariant
    obvious in this test module: engine capability truth must not depend
    on planner strategy."""
    tree = ast.parse(_flow_capability_manifest_source().read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "ai_builder" not in module.split("."), (
                f"forbidden import from ai_builder: {module}"
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "ai_builder" not in alias.name.split("."), (
                    f"forbidden import from ai_builder: {alias.name}"
                )


# ---------------------------------------------------------------------
# FCM CI coverage test.
#
# Walk the full enum cartesian product and classify each cell. Outcomes:
#   - "illegal_io_triple":        `supports_step_io_tuple(it, ot, om) is False`
#   - "illegal_source_type_pair": (input_source, input_type) violates a
#                                  single-cell rule mirrored from
#                                  `step_chain_rules.py` /
#                                  `flow_validators_http.py`
#   - "not_exposed":              owning capability has
#                                 `exposure="not_exposed"` with a permanent
#                                 reason
#   - "exposed":                  owning capabilities are all
#                                 `exposure="builder"`
#
# Temporary reasons (substring match on "temporary") fail CI.
# Unclassified cells fail CI.
# ---------------------------------------------------------------------


def _enumerate_enum_tuples() -> list[
    tuple[FlowInputSource, FlowInputType, FlowOutputType, FlowOutputMode]
]:
    return [
        (is_, it, ot, om)
        for is_ in FlowInputSource
        for it in FlowInputType
        for ot in FlowOutputType
        for om in FlowOutputMode
    ]


def test_every_enum_tuple_is_classified() -> None:
    """Coverage guard. Every 4-tuple in `FlowInputSource × FlowInputType
    × FlowOutputType × FlowOutputMode` must land in one of four buckets:
    exposed, illegal_io_triple, illegal_source_type_pair, or not_exposed
    with a permanent reason.

    A reason containing the literal word "temporary" fails CI — temporary
    exclusions are rejected so nothing can drift into the registry under
    cover of a placeholder reason."""
    cells = _enumerate_enum_tuples()
    total_expected = (
        len(FlowInputSource)
        * len(FlowInputType)
        * len(FlowOutputType)
        * len(FlowOutputMode)
    )
    assert len(cells) == total_expected, (
        f"Cartesian walker missed cells: got {len(cells)} expected {total_expected}"
    )

    classified = {
        "exposed": 0,
        "illegal_io_triple": 0,
        "illegal_source_type_pair": 0,
        "not_exposed": 0,
    }
    temporary_violations: list[str] = []

    for cell in cells:
        outcome, reason = _classify_cell(*cell)
        assert outcome in classified, f"Unknown classification {outcome!r} for {cell}"
        if outcome == "not_exposed":
            if _TEMPORARY_REASON_MARKER in (reason or "").lower():
                temporary_violations.append(
                    f"{cell}: not_exposed_reason contains "
                    f"{_TEMPORARY_REASON_MARKER!r} — temporary exclusions "
                    f"are rejected (reason={reason!r})"
                )
                continue
        classified[outcome] += 1

    assert not temporary_violations, (
        "Cells with temporary not_exposed_reason:\n" + "\n".join(temporary_violations)
    )
    assert sum(classified.values()) == total_expected, (
        f"Classification counts do not sum to matrix size: {classified} "
        f"(expected total={total_expected})"
    )
    # Sanity floors: each bucket holds at least one cell today. If a
    # bucket empties, that's a structural surface shift worth surfacing.
    assert classified["exposed"] > 0
    assert classified["illegal_io_triple"] > 0
    assert classified["illegal_source_type_pair"] > 0
    assert classified["not_exposed"] > 0


# ---------------------------------------------------------------------
# FCM_VERSION bump-discipline.
#
# Compute a structural fingerprint over the bump-relevant fields: keys,
# applies_to_tuples, FlowCapability / nested fields, invariants,
# required_config, CHAIN_COMPATIBILITY, FINAL_OUTPUT_ARTIFACT_BY_TYPE,
# ALLOWED_MCP_POLICIES. Excludes UI prose (label, description,
# not_exposed_reason body) — rewording permanent reasons or labels must
# not bump the version.
#
# Any fingerprint drift requires BOTH a version bump AND a fingerprint
# update. The failure message spells both paths out so future authors
# pick the right one.
# ---------------------------------------------------------------------


def _capability_fingerprint(
    capability: FlowCapability,
) -> tuple[object, ...]:
    """Per-capability bump-relevant fields. `capability.id` is omitted —
    the enclosing registry-key tuple already carries identity. `label` and
    `FlowCapability.description` are also omitted (UI copy; a pure
    rewording must not bump the version). `InvariantSpec.description` IS
    included — it is the rule text itself, not UI copy, so a wording
    change there is a semantic change."""
    return (
        capability.exposure,
        capability.channel,
        capability.runtime_input_mode,
        tuple(
            sorted(
                (is_.value, it.value, ot.value, om.value)
                for is_, it, ot, om in capability.applies_to_tuples
            )
        ),
        tuple(sorted((inv.id, inv.description) for inv in capability.invariants)),
        tuple(sorted(req.key for req in capability.required_config)),
    )


def _compute_fcm_surface_fingerprint() -> tuple[object, ...]:
    """Top-level fingerprint. The first three entries are the dataclass
    field-name tuples for `FlowCapability`, `InvariantSpec`, and
    `ConfigRequirement` — adding, removing, or renaming a field on any of
    the three is a bump-relevant schema change."""
    return (
        tuple(sorted(FlowCapability.__dataclass_fields__.keys())),
        tuple(sorted(InvariantSpec.__dataclass_fields__.keys())),
        tuple(sorted(ConfigRequirement.__dataclass_fields__.keys())),
        tuple(sorted(CAPABILITY_REGISTRY.keys())),
        tuple(
            _capability_fingerprint(CAPABILITY_REGISTRY[key])
            for key in sorted(CAPABILITY_REGISTRY.keys())
        ),
        tuple(sorted((ot.value, it.value) for ot, it in CHAIN_COMPATIBILITY)),
        tuple(
            sorted(
                (ot.value, artifact)
                for ot, artifact in FINAL_OUTPUT_ARTIFACT_BY_TYPE.items()
            )
        ),
    )


_FCM_SURFACE_FINGERPRINT_V7: tuple[object, ...] = (
    (
        "applies_to_tuples",
        "channel",
        "description",
        "exposure",
        "id",
        "invariants",
        "label",
        "not_exposed_reason",
        "required_config",
        "runtime_input_mode",
    ),
    ("description", "id"),
    ("key",),
    (
        "citation_sidecar",
        "input_any",
        "input_audio",
        "input_document",
        "input_file",
        "input_image",
        "input_json",
        "input_text",
        "output_mode_compose_text",
        "output_mode_http_post",
        "output_mode_pass_through",
        "output_mode_render_verbatim",
        "output_mode_template_fill",
        "output_mode_transcribe_only",
        "per_source_reader_execution",
    ),
    (
        (
            "builder",
            None,
            None,
            (),
            (
                (
                    "forbids_template_fill_or_transcribe_only",
                    "Citation capability is disabled when `output_mode` is "
                    "`compose_text`, `template_fill`, `transcribe_only`, or "
                    "`render_verbatim` (non-LLM pathways). "
                    "Any other output_mode preserves capability when the rest holds.",
                ),
                (
                    "requires_citation_capable_output_config",
                    "Citation capability requires `resolve_citation_mode(output_config) "
                    "== 'inline_inref_sidecar'`; any other resolved mode (including "
                    "`off`, missing keys, non-dict payloads) collapses capability to "
                    "`False`.",
                ),
                (
                    "requires_text_output_type",
                    "Citation capability holds only when `output_type=TEXT`; "
                    "`is_citation_capable_step` returns `False` for JSON/PDF/DOCX "
                    "outputs regardless of citation_mode.",
                ),
            ),
            (),
        ),
        (
            "builder",
            "text_only",
            None,
            (),
            (
                (
                    "input_contract_forbidden",
                    "Steps using the `any` input capability must not set "
                    "`input_contract`; the runtime rejects contract on "
                    "non-contract-allowed capabilities.",
                ),
            ),
            (),
        ),
        (
            "builder",
            "text_only",
            "audio",
            (),
            (
                (
                    "input_contract_forbidden",
                    "Steps using the `audio` input capability must not set "
                    "`input_contract`; the runtime rejects contract on "
                    "non-contract-allowed capabilities.",
                ),
                (
                    "requires_enabled_flow_transcription_config",
                    "Flows containing any `AUDIO`-input step require "
                    "`metadata_json.wizard.transcription_enabled=True` and "
                    "a non-null `transcription_model.id`; "
                    "`_validate_audio_transcription_settings` rejects "
                    "missing config for every audio step regardless of `output_mode`.",
                ),
            ),
            (),
        ),
        (
            "builder",
            "text_only",
            "documents",
            (),
            (
                (
                    "input_contract_forbidden",
                    "Steps using the `document` input capability must not set "
                    "`input_contract`; the runtime rejects contract on "
                    "non-contract-allowed capabilities.",
                ),
                (
                    "requires_non_empty_extraction",
                    "Steps using the `document` input capability must produce "
                    "non-empty extracted text at runtime; empty extraction is "
                    "rejected by `validate_runtime_input_policy`.",
                ),
            ),
            (),
        ),
        (
            "builder",
            "text_only",
            "documents",
            (),
            (
                (
                    "input_contract_forbidden",
                    "Steps using the `file` input capability must not set "
                    "`input_contract`; the runtime rejects contract on "
                    "non-contract-allowed capabilities.",
                ),
                (
                    "requires_non_empty_extraction",
                    "Steps using the `file` input capability must produce non-empty "
                    "extracted text at runtime; empty extraction is rejected by "
                    "`validate_runtime_input_policy`.",
                ),
            ),
            (),
        ),
        (
            "not_exposed",
            "files_only",
            None,
            (),
            (
                (
                    "input_contract_forbidden",
                    "Steps using the `image` input capability must not set "
                    "`input_contract`; the runtime rejects contract on "
                    "non-contract-allowed capabilities.",
                ),
                (
                    "requires_at_least_one_file",
                    "Steps using the `image` input capability must present at least "
                    "one compatible file at runtime.",
                ),
            ),
            (),
        ),
        ("builder", "text_only", "text", (), (), ()),
        ("builder", "text_only", "text", (), (), ()),
        (
            "builder",
            None,
            None,
            (),
            (
                (
                    "requires_text_input_text_output",
                    "Steps using `compose_text` must have `input_type=TEXT` and "
                    "`output_type=TEXT`; any other IO pair is rejected by "
                    "`supports_step_io_tuple`.",
                ),
            ),
            (),
        ),
        (
            "builder",
            None,
            None,
            (),
            (
                (
                    "requires_http_output_config",
                    "Steps using `http_post` output mode must declare an "
                    "`output_config` object that passes `validate_http_output_config`; "
                    "the authored HTTP transport config is the only accepted shape. "
                    "The capability does not pin per-field rules — see the transport "
                    "validators for URL scheme, body-mode, auth, and timeout "
                    "constraints.",
                ),
            ),
            (),
        ),
        (
            "builder",
            None,
            None,
            (),
            (
                (
                    "forbids_text_document_render_path",
                    "Steps with `input_type=TEXT` and `output_type=PDF` or "
                    "`DOCX` cannot use `pass_through`; direct text-to-document "
                    "rendering is owned by `render_verbatim`.",
                ),
            ),
            (),
        ),
        (
            "builder",
            None,
            None,
            (),
            (
                (
                    "forbids_output_contract",
                    "Steps using `render_verbatim` render resolved text directly "
                    "and must not declare an `output_contract`.",
                ),
                (
                    "requires_text_input_document_output",
                    "Steps using `render_verbatim` must have `input_type=TEXT` "
                    "and `output_type=PDF` or `DOCX`; any other IO pair is "
                    "rejected by `supports_step_io_tuple`.",
                ),
            ),
            (),
        ),
        (
            "builder",
            None,
            None,
            (),
            (
                (
                    "forbids_output_contract",
                    "Steps using `template_fill` must not declare an "
                    "`output_contract`; `_validate_output_contract_compatibility` "
                    "raises when the mode and contract coexist.",
                ),
                (
                    "requires_docx_output_type",
                    "Steps using `template_fill` must have `output_type=DOCX`; "
                    "`supports_step_io_tuple` rejects other output types.",
                ),
                (
                    "requires_template_fill_output_config",
                    "Publishable flows with a `template_fill` step require a "
                    "complete `output_config` template block; "
                    "`validate_template_fill_output_config` enforces this when "
                    "`require_complete_template_fill_config=True`.",
                ),
            ),
            (),
        ),
        (
            "builder",
            None,
            None,
            (),
            (
                (
                    "requires_audio_input_text_output",
                    "Steps using `transcribe_only` must have `input_type=AUDIO` and "
                    "`output_type=TEXT`; any other IO pair is rejected by "
                    "`supports_step_io_tuple`.",
                ),
                (
                    "requires_audio_runtime_input_format",
                    "Steps using `transcribe_only` with runtime_input enabled must "
                    "declare `input_format='audio'`; "
                    "`_validate_runtime_input_publish_rules` rejects other formats.",
                ),
            ),
            (),
        ),
        (
            "builder",
            None,
            None,
            (),
            (
                (
                    "bounded_concurrent_source_calls",
                    "Source calls are mapped with a named runtime concurrency "
                    "bound and fail-fast at step-attempt granularity.",
                ),
                (
                    "requires_documents_array_contract",
                    "Per-source reader execution requires a JSON output contract "
                    "shaped as exactly one top-level `documents[]` array; "
                    "corpus-level synthesis belongs to a downstream writer step.",
                ),
                (
                    "runtime_sets_source_identity",
                    "The runtime, not the model, sets `source_label` and "
                    "`source_file_id` from uploaded file metadata before assembling "
                    "the final documents[] payload.",
                ),
            ),
            ("input_config.runtime_input.execution_mode",),
        ),
    ),
    (
        ("docx", "any"),
        ("docx", "text"),
        ("json", "any"),
        ("json", "json"),
        ("json", "text"),
        ("pdf", "any"),
        ("pdf", "text"),
        ("text", "any"),
        ("text", "json"),
        ("text", "text"),
    ),
    (
        ("docx", "docx_document"),
        ("json", "structured_json"),
        ("pdf", "pdf_document"),
        ("text", "structured_text"),
    ),
)


def test_fcm_surface_fingerprint_is_stable() -> None:
    """Bump-discipline guard.

    The fingerprint captures bump-relevant fields: dataclass field sets
    for `FlowCapability`, `InvariantSpec`, and `ConfigRequirement` (so
    adding/removing a field on any of those shows up), capability keys,
    exposure, channel, runtime_input_mode, applies_to_tuples,
    `(invariant_id, invariant_description)` pairs, required_config keys,
    CHAIN_COMPATIBILITY and FINAL_OUTPUT_ARTIFACT_BY_TYPE. It intentionally
    excludes `FlowCapability.label`,
    `FlowCapability.description`, and `not_exposed_reason` bodies so
    rewording UI copy does not force a bump.

    If this test fails with an actual != expected diff, bump
    `FCM_VERSION` to the next integer AND update the fingerprint constant.
    Rename the constant to `_FCM_SURFACE_FINGERPRINT_V<N>` so the history
    reads cleanly.
    """
    actual = _compute_fcm_surface_fingerprint()
    assert actual == _FCM_SURFACE_FINGERPRINT_V7, (
        "FCM surface fingerprint drifted. Bump `FCM_VERSION` to "
        f"{FCM_VERSION + 1} and update the expected fingerprint constant "
        "in this test.\n\n"
        f"Expected: {_FCM_SURFACE_FINGERPRINT_V7}\n\n"
        f"Actual:   {actual}"
    )


# ---------------------------------------------------------------------
# FCM public API tests.
#
# Public fns: resolve_capability_for_tuple, coverage_report.
# Public shape: CoverageReport.
# ---------------------------------------------------------------------


class TestResolveCapabilityForTuple:
    """Tuple-to-capability lookup — returns the owning (input, output_mode)
    capability pair for legal cells; None otherwise."""

    def test_legal_exposed_tuple_returns_owning_caps(self) -> None:
        caps = resolve_capability_for_tuple(
            input_source=FlowInputSource.FLOW_INPUT,
            input_type=FlowInputType.TEXT,
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )
        assert caps is not None
        assert len(caps) == 2
        ids = [cap.id for cap in caps]
        assert ids == ["input_text", "output_mode_pass_through"]

    def test_json_to_json_flow_input_tuple_returns_owning_caps(self) -> None:
        caps = resolve_capability_for_tuple(
            input_source=FlowInputSource.FLOW_INPUT,
            input_type=FlowInputType.JSON,
            output_type=FlowOutputType.JSON,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )

        assert caps is not None
        ids = [cap.id for cap in caps]
        assert ids == ["input_json", "output_mode_pass_through"]

    def test_illegal_io_triple_returns_none(self) -> None:
        # TEMPLATE_FILL is only legal on DOCX output.
        assert (
            resolve_capability_for_tuple(
                input_source=FlowInputSource.FLOW_INPUT,
                input_type=FlowInputType.TEXT,
                output_type=FlowOutputType.TEXT,
                output_mode=FlowOutputMode.TEMPLATE_FILL,
            )
            is None
        )

    def test_text_document_pass_through_tuple_returns_none(self) -> None:
        assert (
            resolve_capability_for_tuple(
                input_source=FlowInputSource.FLOW_INPUT,
                input_type=FlowInputType.TEXT,
                output_type=FlowOutputType.PDF,
                output_mode=FlowOutputMode.PASS_THROUGH,
            )
            is None
        )

    def test_illegal_source_type_pair_returns_none(self) -> None:
        # DOCUMENT input requires FLOW_INPUT source.
        assert (
            resolve_capability_for_tuple(
                input_source=FlowInputSource.PREVIOUS_STEP,
                input_type=FlowInputType.DOCUMENT,
                output_type=FlowOutputType.TEXT,
                output_mode=FlowOutputMode.PASS_THROUGH,
            )
            is None
        )

    def test_not_exposed_input_returns_none(self) -> None:
        # IMAGE input is `not_exposed` — builder must not surface a capability.
        assert (
            resolve_capability_for_tuple(
                input_source=FlowInputSource.FLOW_INPUT,
                input_type=FlowInputType.IMAGE,
                output_type=FlowOutputType.TEXT,
                output_mode=FlowOutputMode.PASS_THROUGH,
            )
            is None
        )

    def test_http_output_mode_legal_tuple_returns_caps(self) -> None:
        caps = resolve_capability_for_tuple(
            input_source=FlowInputSource.FLOW_INPUT,
            input_type=FlowInputType.TEXT,
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.HTTP_POST,
        )
        assert caps is not None
        ids = [cap.id for cap in caps]
        assert ids == ["input_text", "output_mode_http_post"]

    def test_compose_text_legal_tuple_returns_caps(self) -> None:
        caps = resolve_capability_for_tuple(
            input_source=FlowInputSource.PREVIOUS_STEP,
            input_type=FlowInputType.TEXT,
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.COMPOSE_TEXT,
        )
        assert caps is not None
        ids = [cap.id for cap in caps]
        assert ids == ["input_text", "output_mode_compose_text"]

    def test_transcribe_only_legal_tuple_returns_caps(self) -> None:
        caps = resolve_capability_for_tuple(
            input_source=FlowInputSource.FLOW_INPUT,
            input_type=FlowInputType.AUDIO,
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.TRANSCRIBE_ONLY,
        )
        assert caps is not None
        ids = [cap.id for cap in caps]
        assert ids == ["input_audio", "output_mode_transcribe_only"]

    def test_template_fill_docx_legal_tuple_returns_caps(self) -> None:
        caps = resolve_capability_for_tuple(
            input_source=FlowInputSource.FLOW_INPUT,
            input_type=FlowInputType.TEXT,
            output_type=FlowOutputType.DOCX,
            output_mode=FlowOutputMode.TEMPLATE_FILL,
        )
        assert caps is not None
        ids = [cap.id for cap in caps]
        assert ids == ["input_text", "output_mode_template_fill"]

    def test_render_verbatim_pdf_legal_tuple_returns_caps(self) -> None:
        caps = resolve_capability_for_tuple(
            input_source=FlowInputSource.PREVIOUS_STEP,
            input_type=FlowInputType.TEXT,
            output_type=FlowOutputType.PDF,
            output_mode=FlowOutputMode.RENDER_VERBATIM,
        )
        assert caps is not None
        ids = [cap.id for cap in caps]
        assert ids == ["input_text", "output_mode_render_verbatim"]


class TestCoverageReport:
    """Summary of the FCM cell-coverage walk. Used by CI drift guards."""

    def test_total_cells_matches_cartesian(self) -> None:
        report = coverage_report()
        assert report.total_cells == (
            len(FlowInputSource)
            * len(FlowInputType)
            * len(FlowOutputType)
            * len(FlowOutputMode)
        )

    def test_classification_counts_sum_to_total(self) -> None:
        report = coverage_report()
        assert sum(report.by_classification.values()) == report.total_cells

    def test_by_classification_covers_four_buckets(self) -> None:
        report = coverage_report()
        assert set(report.by_classification) == {
            "exposed",
            "illegal_io_triple",
            "illegal_source_type_pair",
            "not_exposed",
        }
        for count in report.by_classification.values():
            assert count > 0

    def test_has_no_drift_on_current_registry(self) -> None:
        report = coverage_report()
        assert report.has_drift is False
        assert report.temporary_reasons == ()

    def test_coverage_report_is_frozen_dataclass(self) -> None:
        report = coverage_report()
        assert isinstance(report, CoverageReport)
        with pytest.raises(FrozenInstanceError):
            report.total_cells = 0  # type: ignore[misc]
