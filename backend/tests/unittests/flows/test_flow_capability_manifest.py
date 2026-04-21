"""FCM scaffold (Phase A.0).

Covers: version constant, dataclass shape (engine-truth fields only),
registry seeding from `INPUT_TYPE_POLICIES`, and the `not_exposed_reason`
invariant. Chain validation, tuple-matrix coverage, and critic invariants
land with A.1 / A.3 and are deliberately out of scope here.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from intric.flows.ai_builder.ai_builder_step_capabilities import (
    BUILDER_FINAL_OUTPUT_ARTIFACT_BY_OUTPUT_TYPE,
    BUILDER_RUNTIME_INPUT_MODE_BY_INPUT_TYPE,
)
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    is_citation_capable_step as _legacy_is_citation_capable_step,
)
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    resolve_document_generation_mode as _legacy_resolve_document_generation_mode,
)
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    supports_step_io_mode_combo as _legacy_supports_step_io_mode_combo,
)
from intric.flows.citation_sidecar import CITATION_MODE_INLINE_INREF_SIDECAR
from intric.flows.enums import FlowInputType, FlowOutputMode, FlowOutputType
from intric.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    CHAIN_COMPATIBILITY,
    FCM_VERSION,
    FINAL_OUTPUT_ARTIFACT_BY_TYPE,
    FlowCapability,
    is_citation_capable_step,
    resolve_document_generation_mode,
    supports_step_io_tuple,
)
from intric.flows.step_chain_rules import COMPATIBLE_TYPE_COERCIONS
from intric.flows.type_policies import INPUT_TYPE_POLICIES


def _flow_capability_manifest_source() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "src"
        / "intric"
        / "flows"
        / "flow_capability_manifest.py"
    )


def test_fcm_version_is_one() -> None:
    assert FCM_VERSION == 1


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
    from intric.flows.flow_capability_manifest import CAPABILITY_REGISTRY

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


def test_chain_compatibility_mirrors_legacy_compatible_type_coercions() -> None:
    """Parity test. Phase A.1a mirrors `COMPATIBLE_TYPE_COERCIONS` into the
    FCM without touching consumers; the two sets must stay in lockstep
    until Phase G deletes the legacy table. A drift here is a bug."""
    fcm_as_strings = {(out.value, inp.value) for out, inp in CHAIN_COMPATIBILITY}
    assert fcm_as_strings == COMPATIBLE_TYPE_COERCIONS, (
        "CHAIN_COMPATIBILITY has drifted from COMPATIBLE_TYPE_COERCIONS.\n"
        f"Missing from FCM: {COMPATIBLE_TYPE_COERCIONS - fcm_as_strings}\n"
        f"Extra in FCM:    {fcm_as_strings - COMPATIBLE_TYPE_COERCIONS}"
    )


@pytest.mark.parametrize("input_key", sorted(INPUT_TYPE_POLICIES.keys()))
def test_capability_channel_mirrors_policy(input_key: str) -> None:
    """A.1b: every seeded input capability carries the same `channel` as its
    `InputTypePolicy`. FCM is the typed mirror; `type_policies.py` remains
    the editable source until Phase G."""
    policy = INPUT_TYPE_POLICIES[input_key]
    capability = CAPABILITY_REGISTRY[f"input_{input_key}"]
    assert capability.channel == policy.channel


@pytest.mark.parametrize("input_key", sorted(INPUT_TYPE_POLICIES.keys()))
def test_capability_invariants_track_policy_flags(input_key: str) -> None:
    """A.1b: each of the three policy-derived invariants is present iff
    the corresponding flag on `InputTypePolicy` demands it. Drift between
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
    """A.1b symmetric guard: every `input_*` capability must declare a
    channel. `channel=None` is valid for future non-input capabilities
    (citation, transcription wizard, MCP) but never for an input
    capability — the runtime uses `channel` to decide whether to forward
    file bytes to the LLM."""
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


def test_input_text_has_no_absorbed_invariants() -> None:
    """Positive guardrail: `input_text` has `contract_allowed=True`,
    `requires_extraction=False`, `requires_files=False` → zero absorbed
    invariants. Catches a future seeder bug that would add spurious
    invariants where the policy has none."""
    capability = CAPABILITY_REGISTRY["input_text"]
    assert capability.invariants == ()
    assert capability.channel == "text_only"


@pytest.mark.parametrize("input_key", sorted(INPUT_TYPE_POLICIES.keys()))
def test_capability_runtime_input_mode_mirrors_builder_map(input_key: str) -> None:
    """A.1c: every seeded `input_*` capability carries `runtime_input_mode`
    matching `BUILDER_RUNTIME_INPUT_MODE_BY_INPUT_TYPE.get(key)`. The legacy
    map covers 5 of 7 input types (image/any are absent) — the capability
    field must be `None` for those so the typed mirror doesn't invent
    behaviour the runtime doesn't support."""
    capability = CAPABILITY_REGISTRY[f"input_{input_key}"]
    expected = BUILDER_RUNTIME_INPUT_MODE_BY_INPUT_TYPE.get(input_key)
    assert capability.runtime_input_mode == expected


def test_final_output_artifact_by_type_mirrors_legacy() -> None:
    """A.1c parity: `FINAL_OUTPUT_ARTIFACT_BY_TYPE` (typed with `FlowOutputType`
    keys + `OutputArtifact` literal values) must stay in lockstep with the
    legacy `BUILDER_FINAL_OUTPUT_ARTIFACT_BY_OUTPUT_TYPE` string-dict until
    Phase G deletes the legacy source. Drift is a bug."""
    fcm_as_strings = {
        out_type.value: artifact
        for out_type, artifact in FINAL_OUTPUT_ARTIFACT_BY_TYPE.items()
    }
    assert fcm_as_strings == BUILDER_FINAL_OUTPUT_ARTIFACT_BY_OUTPUT_TYPE, (
        "FINAL_OUTPUT_ARTIFACT_BY_TYPE has drifted from "
        "BUILDER_FINAL_OUTPUT_ARTIFACT_BY_OUTPUT_TYPE."
    )


def test_final_output_artifact_by_type_is_frozen_and_typed_with_enums() -> None:
    """A.1c: the FCM mirror must be an immutable `Mapping` keyed by
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


@pytest.mark.parametrize("input_type", [None, *list(FlowInputType)])
@pytest.mark.parametrize("output_type", list(FlowOutputType))
@pytest.mark.parametrize("output_mode", list(FlowOutputMode))
def test_supports_step_io_tuple_parity_with_legacy(
    input_type: FlowInputType | None,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> None:
    """A.1d parity: `supports_step_io_tuple` (enum-typed, engine-side) must
    agree with legacy `supports_step_io_mode_combo` (string-typed, ai_builder)
    on every (input_type, output_type, output_mode) triple. Covers None for
    input_type — the legacy signature allows it, and the FCM must too."""
    fcm_result = supports_step_io_tuple(
        input_type=input_type, output_type=output_type, output_mode=output_mode
    )
    legacy_result = _legacy_supports_step_io_mode_combo(
        input_type=input_type.value if input_type is not None else None,
        output_type=output_type.value,
        output_mode=output_mode.value,
    )
    assert fcm_result is legacy_result, (
        f"supports_step_io_tuple drift: "
        f"input={input_type} output={output_type} mode={output_mode} "
        f"fcm={fcm_result} legacy={legacy_result}"
    )


@pytest.mark.parametrize("output_type", list(FlowOutputType))
@pytest.mark.parametrize("output_mode", list(FlowOutputMode))
def test_resolve_document_generation_mode_parity_with_legacy(
    output_type: FlowOutputType, output_mode: FlowOutputMode
) -> None:
    """A.1d parity: FCM `resolve_document_generation_mode` returns the same
    `DocumentGenerationMode | None` as the legacy ai_builder version for every
    (output_type, output_mode) pair."""
    fcm_result = resolve_document_generation_mode(
        output_type=output_type, output_mode=output_mode
    )
    legacy_result = _legacy_resolve_document_generation_mode(
        output_type=output_type.value, output_mode=output_mode.value
    )
    assert fcm_result == legacy_result, (
        f"resolve_document_generation_mode drift: "
        f"output={output_type} mode={output_mode} "
        f"fcm={fcm_result} legacy={legacy_result}"
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


_CITATION_CONFIG_CASES: tuple[tuple[str, object], ...] = (
    ("enabled_sidecar", {"citation_mode": CITATION_MODE_INLINE_INREF_SIDECAR}),
    # Whitespace-padded value covers `resolve_citation_mode`'s `.strip()`
    # branch — the FCM predicate relies on that normalisation and must not
    # regress if someone later inlines a raw equality check.
    ("enabled_whitespace_padded", {"citation_mode": "  inline_inref_sidecar  "}),
    ("disabled_off", {"citation_mode": "off"}),
    # Non-string value covers `resolve_citation_mode`'s `isinstance(..., str)`
    # guard; must resolve to OFF regardless of the rest of the step.
    ("non_string_value", {"citation_mode": 1}),
    ("empty_dict", {}),
    ("non_dict_none", None),
)


@pytest.mark.parametrize(
    "config_label,output_config",
    _CITATION_CONFIG_CASES,
    ids=[c[0] for c in _CITATION_CONFIG_CASES],
)
@pytest.mark.parametrize("output_type", list(FlowOutputType))
@pytest.mark.parametrize("output_mode", list(FlowOutputMode))
def test_is_citation_capable_step_parity_with_legacy(
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
    config_label: str,
    output_config: object,
) -> None:
    """Parity: FCM `is_citation_capable_step` (enum-typed, engine-side) must
    agree with the legacy `ai_builder` version (string-typed) on every
    (output_type, output_mode, citation-config) combination. Covers the four
    representative citation configs: enabled sidecar, explicit off, empty
    dict, and a non-dict sentinel — matching the branch structure of
    `resolve_citation_mode`."""
    fcm_result = is_citation_capable_step(
        output_type=output_type,
        output_mode=output_mode,
        output_config=output_config,
    )
    legacy_result = _legacy_is_citation_capable_step(
        output_type=output_type.value,
        output_mode=output_mode.value,
        output_config=output_config,
    )
    assert fcm_result is legacy_result, (
        f"is_citation_capable_step drift: output={output_type} "
        f"mode={output_mode} config={config_label} "
        f"fcm={fcm_result} legacy={legacy_result}"
    )


def test_is_citation_capable_step_requires_inline_inref_sidecar_mode() -> None:
    """Explicit rule guardrail: only `inline_inref_sidecar` citation mode
    unlocks citation capability. Any other recognisable mode (including the
    explicit 'off' sentinel and an unknown mode string) must return False
    even when the rest of the step is citation-friendly."""
    for bad_mode in ("off", "unknown_mode", "", "inline", "sidecar"):
        assert (
            is_citation_capable_step(
                output_type=FlowOutputType.TEXT,
                output_mode=FlowOutputMode.PASS_THROUGH,
                output_config={"citation_mode": bad_mode},
            )
            is False
        ), f"non-sidecar citation_mode={bad_mode!r} must not unlock capability"


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
    `TEMPLATE_FILL` and `TRANSCRIBE_ONLY` output modes must reject citation
    capability — template-fill is a docx-artefact mode and transcription is
    citation-naive at the wizard level."""
    enabled_config = {"citation_mode": CITATION_MODE_INLINE_INREF_SIDECAR}
    for output_mode in FlowOutputMode:
        result = is_citation_capable_step(
            output_type=FlowOutputType.TEXT,
            output_mode=output_mode,
            output_config=enabled_config,
        )
        expected = output_mode not in {
            FlowOutputMode.TEMPLATE_FILL,
            FlowOutputMode.TRANSCRIBE_ONLY,
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


# A.1f — output-mode + citation capability registry entries -------------
#
# These tests pin the capability IDs and invariant-ID sets that FCM must
# declare for each `FlowOutputMode` + the citation sidecar. The invariant
# IDs are grep-matched against the legacy error phrases in
# `flow_validators.py:validate_steps` so A.2's un-invert knows which
# capability carries each rule.


_EXPECTED_OUTPUT_MODE_CAPABILITIES: dict[FlowOutputMode, tuple[str, frozenset[str]]] = {
    FlowOutputMode.PASS_THROUGH: ("output_mode_pass_through", frozenset()),
    FlowOutputMode.HTTP_POST: (
        "output_mode_http_post",
        frozenset({"requires_http_output_config"}),
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
    be citation-capable. Separate from the `is_citation_capable_step` FCM
    function (A.1e) which is a step-level predicate."""
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
    `input_audio` capability. A.2 consumers that apply invariants by
    capability ownership must reject pass-through audio steps with
    disabled transcription just like transcribe-only ones."""
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
    assert non_input_ids  # sanity: A.1f actually added entries
    for cap_id in non_input_ids:
        capability = CAPABILITY_REGISTRY[cap_id]
        assert capability.channel is None, (
            f"{cap_id} is not an input capability; channel must be None"
        )
        assert capability.runtime_input_mode is None, (
            f"{cap_id} is not an input capability; runtime_input_mode must be None"
        )


def test_fcm_module_has_no_ai_builder_imports() -> None:
    """Redundant with the P0.7 `importlinter` contract but keeps the invariant
    obvious in this test module: engine capability truth must not depend on
    planner strategy."""
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
