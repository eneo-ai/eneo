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
    resolve_document_generation_mode as _legacy_resolve_document_generation_mode,
)
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    supports_step_io_mode_combo as _legacy_supports_step_io_mode_combo,
)
from intric.flows.enums import FlowInputType, FlowOutputMode, FlowOutputType
from intric.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    CHAIN_COMPATIBILITY,
    FCM_VERSION,
    FINAL_OUTPUT_ARTIFACT_BY_TYPE,
    FlowCapability,
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
