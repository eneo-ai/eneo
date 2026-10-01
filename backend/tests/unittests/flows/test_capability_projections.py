"""The capability manifest owns three projections of one contract.

inspectable: the tuple shapes the manifest rules admit as persisted step
shapes, including HTTP and image shapes (image is still rejected at graph
validation as unsupported input). editable_existing: the cells an authoring
spec can carry. proposable_new: the cells the AI Builder may propose. Each is derived from the same legality functions; the checks below
recompute legality independently of the manifest.
"""

from __future__ import annotations

from itertools import product

import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.planning_state import PlanningState, StepTriple
from eneo.flows.enums import (
    FlowAuthoringInputSource,
    FlowAuthoringInputType,
    FlowAuthoringOutputMode,
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    FCM_VERSION,
    CapabilityProjection,
    coverage_report,
    projection_cells,
    projection_values,
    resolve_capability_for_tuple,
    supports_step_io_tuple,
)
from eneo.flows.output_modes import speaker_mapping_violation

Cell = tuple[FlowInputSource, FlowInputType, FlowOutputType, FlowOutputMode]

ALL_CELLS: tuple[Cell, ...] = tuple(
    product(FlowInputSource, FlowInputType, FlowOutputType, FlowOutputMode)
)
AXES = ("input_source", "input_type", "output_type", "output_mode")
AUTHORABLE: tuple[frozenset[str], ...] = (
    frozenset(item.value for item in FlowAuthoringInputSource),
    frozenset(item.value for item in FlowAuthoringInputType),
    frozenset(item.value for item in FlowOutputType),
    frozenset(item.value for item in FlowAuthoringOutputMode),
)


def _legal(cell: Cell) -> bool:
    """Legality of one step on its own, without input bindings: the platform's
    own IO and speaker-mapping rules, plus the three single-cell source/type
    rules stated here as plain facts."""
    source, input_type, output_type, output_mode = cell
    if not supports_step_io_tuple(
        input_type=input_type, output_type=output_type, output_mode=output_mode
    ):
        return False
    if (
        speaker_mapping_violation(
            step_order=1,
            input_source=source,
            input_type=input_type,
            output_type=output_type,
            output_mode=output_mode,
        )
        is not None
    ):
        return False
    if source is FlowInputSource.HTTP_GET and input_type in {
        FlowInputType.DOCUMENT,
        FlowInputType.FILE,
        FlowInputType.IMAGE,
        FlowInputType.AUDIO,
    }:
        return False
    if (
        input_type in {FlowInputType.DOCUMENT, FlowInputType.AUDIO, FlowInputType.FILE}
        and source is not FlowInputSource.FLOW_INPUT
    ):
        return False
    return not (
        input_type is FlowInputType.JSON
        and source is FlowInputSource.ALL_PREVIOUS_STEPS
    )


def _authorable(cell: Cell) -> bool:
    return all(member.value in allowed for member, allowed in zip(cell, AUTHORABLE))


def _triples(cells: frozenset[Cell]) -> set[tuple[str, str, str]]:
    return {(c[1].value, c[2].value, c[3].value) for c in cells}


LEGAL_CELLS = frozenset(cell for cell in ALL_CELLS if _legal(cell))


def test_inspectable_is_every_cell_the_listed_rules_admit() -> None:
    inspectable = projection_cells(CapabilityProjection.INSPECTABLE)
    assert inspectable == LEGAL_CELLS
    assert (len(inspectable), len(_triples(inspectable))) == (159, 66)


def test_http_cells_stay_inspectable() -> None:
    inspectable = projection_cells(CapabilityProjection.INSPECTABLE)
    http = {
        cell
        for cell in inspectable
        if FlowInputSource.HTTP_GET in cell or FlowOutputMode.HTTP_POST in cell
    }
    assert len(http) == 84
    assert any(FlowInputType.IMAGE in cell for cell in inspectable)


def test_editable_existing_is_what_an_authoring_spec_can_carry() -> None:
    editable = projection_cells(CapabilityProjection.EDITABLE_EXISTING)
    assert editable == frozenset(cell for cell in LEGAL_CELLS if _authorable(cell))
    assert (len(editable), len(_triples(editable))) == (60, 33)


@pytest.mark.parametrize(
    ("source", "editable"),
    [
        (FlowInputSource.PREVIOUS_STEP, True),
        (FlowInputSource.FLOW_INPUT, False),
        (FlowInputSource.ALL_PREVIOUS_STEPS, False),
    ],
)
def test_speaker_mapping_is_editable_only_on_the_transcript_step_source(
    source: FlowInputSource, editable: bool
) -> None:
    cell = (
        source,
        FlowInputType.TEXT,
        FlowOutputType.JSON,
        FlowOutputMode.SPEAKER_MAPPING,
    )
    assert (
        cell in projection_cells(CapabilityProjection.EDITABLE_EXISTING)
    ) is editable
    assert (cell in projection_cells(CapabilityProjection.INSPECTABLE)) is editable


def test_proposable_new_is_what_the_builder_may_author_from_scratch() -> None:
    proposable = projection_cells(CapabilityProjection.PROPOSABLE_NEW)
    assert (len(proposable), len(_triples(proposable))) == (59, 32)
    for cell in proposable:
        assert FlowInputSource.HTTP_GET not in cell
        assert FlowOutputMode.HTTP_POST not in cell
        assert FlowOutputMode.SPEAKER_MAPPING not in cell
        assert FlowInputType.IMAGE not in cell


def test_projections_nest() -> None:
    inspectable = projection_cells(CapabilityProjection.INSPECTABLE)
    editable = projection_cells(CapabilityProjection.EDITABLE_EXISTING)
    proposable = projection_cells(CapabilityProjection.PROPOSABLE_NEW)
    assert proposable < editable < inspectable


def test_coverage_report_exposed_is_exactly_proposable_new() -> None:
    report = coverage_report()
    assert dict(report.by_classification) == {
        "exposed": 59,
        "not_exposed": 100,
        "illegal_io_triple": 520,
        "illegal_source_type_pair": 105,
    }
    assert report.has_drift is False


@pytest.mark.parametrize("projection", list(CapabilityProjection))
@pytest.mark.parametrize("axis_index", range(4))
def test_projection_values_follow_enum_declaration_order(
    projection: CapabilityProjection, axis_index: int
) -> None:
    cells = projection_cells(projection)
    enum = (FlowInputSource, FlowInputType, FlowOutputType, FlowOutputMode)[axis_index]
    expected = tuple(
        member.value
        for member in enum
        if any(cell[axis_index] is member for cell in cells)
    )
    assert projection_values(projection, AXES[axis_index]) == expected


def test_proposable_vocabulary_values() -> None:
    values = {
        axis: projection_values(CapabilityProjection.PROPOSABLE_NEW, axis)
        for axis in AXES
    }
    assert values == {
        "input_source": ("flow_input", "previous_step", "all_previous_steps"),
        "input_type": ("text", "json", "audio", "document", "file", "any"),
        "output_type": ("text", "json", "pdf", "docx"),
        "output_mode": (
            "pass_through",
            "compose_text",
            "transcribe_only",
            "template_fill",
            "render_verbatim",
        ),
    }


def test_editable_vocabulary_adds_only_speaker_mapping() -> None:
    proposable = projection_values(CapabilityProjection.PROPOSABLE_NEW, "output_mode")
    editable = projection_values(CapabilityProjection.EDITABLE_EXISTING, "output_mode")
    assert set(editable) - set(proposable) == {"speaker_mapping"}
    for axis in ("input_source", "input_type", "output_type"):
        assert projection_values(
            CapabilityProjection.EDITABLE_EXISTING, axis
        ) == projection_values(CapabilityProjection.PROPOSABLE_NEW, axis)


def test_every_axis_value_outside_the_authoring_enums_has_a_not_exposed_reason() -> (
    None
):
    """The exposure states the truth: a legal cell holding http_get, http_post
    or image is not proposable, with a stated reason, never silently."""
    outside = [cell for cell in LEGAL_CELLS if not _authorable(cell)]
    assert outside
    for cell in outside:
        assert (
            resolve_capability_for_tuple(
                input_source=cell[0],
                input_type=cell[1],
                output_type=cell[2],
                output_mode=cell[3],
            )
            is None
        )


# -- Registry -----------------------------------------------------------------


def _input_capability_cells(input_type: FlowInputType) -> frozenset[Cell]:
    return frozenset(cell for cell in LEGAL_CELLS if cell[1] is input_type)


def _mode_capability_cells(output_mode: FlowOutputMode) -> frozenset[Cell]:
    return frozenset(cell for cell in LEGAL_CELLS if cell[3] is output_mode)


@pytest.mark.parametrize("input_type", list(FlowInputType))
def test_input_capability_applies_to_its_legal_cells(input_type: FlowInputType) -> None:
    capability = CAPABILITY_REGISTRY[f"input_{input_type.value}"]
    assert frozenset(capability.applies_to_tuples) == _input_capability_cells(
        input_type
    )
    assert len(capability.applies_to_tuples) == len(set(capability.applies_to_tuples))


@pytest.mark.parametrize("output_mode", list(FlowOutputMode))
def test_output_mode_capability_applies_to_its_legal_cells(
    output_mode: FlowOutputMode,
) -> None:
    capability = CAPABILITY_REGISTRY[f"output_mode_{output_mode.value}"]
    assert frozenset(capability.applies_to_tuples) == _mode_capability_cells(
        output_mode
    )


def test_capabilities_not_conditioned_on_the_four_tuple_stay_empty() -> None:
    assert CAPABILITY_REGISTRY["citation_sidecar"].applies_to_tuples == ()
    assert CAPABILITY_REGISTRY["per_source_reader_execution"].applies_to_tuples == ()


def test_capability_ids_are_unchanged() -> None:
    assert sorted(CAPABILITY_REGISTRY) == sorted(
        [
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
            "output_mode_speaker_mapping",
            "output_mode_template_fill",
            "output_mode_transcribe_only",
            "per_source_reader_execution",
        ]
    )


def test_descriptions_are_distinct_facts_not_placeholders() -> None:
    descriptions = [
        capability.description for capability in CAPABILITY_REGISTRY.values()
    ]
    assert len(descriptions) == len(set(descriptions)) == 16
    assert not any("Seeded from" in description for description in descriptions)


def test_http_post_exposure_matches_the_builder_vocabulary() -> None:
    capability = CAPABILITY_REGISTRY["output_mode_http_post"]
    assert capability.exposure == "not_exposed"
    assert capability.not_exposed_reason


# -- Readers ------------------------------------------------------------------


def test_resolution_inside_the_authoring_enums_follows_proposable_new() -> None:
    proposable = projection_cells(CapabilityProjection.PROPOSABLE_NEW)
    authorable = [cell for cell in ALL_CELLS if _authorable(cell)]
    assert len(authorable) == 432
    for cell in authorable:
        resolved = resolve_capability_for_tuple(
            input_source=cell[0],
            input_type=cell[1],
            output_type=cell[2],
            output_mode=cell[3],
        )
        if cell in proposable:
            assert resolved is not None
            assert [capability.id for capability in resolved] == [
                f"input_{cell[1].value}",
                f"output_mode_{cell[3].value}",
            ]
        else:
            assert resolved is None


def test_http_cells_no_longer_resolve() -> None:
    http = [
        cell
        for cell in LEGAL_CELLS
        if FlowInputSource.HTTP_GET in cell or FlowOutputMode.HTTP_POST in cell
    ]
    assert http
    for cell in http:
        assert (
            resolve_capability_for_tuple(
                input_source=cell[0],
                input_type=cell[1],
                output_type=cell[2],
                output_mode=cell[3],
            )
            is None
        )


@pytest.mark.parametrize(
    "output_mode",
    projection_values(CapabilityProjection.PROPOSABLE_NEW, "output_mode"),
)
def test_step_triple_accepts_every_proposable_mode(output_mode: str) -> None:
    triple = StepTriple.model_validate(
        {"input_type": "text", "output_type": "text", "output_mode": output_mode}
    )
    assert triple.output_mode.value == output_mode


@pytest.mark.parametrize("output_mode", ["speaker_mapping", "http_post"])
def test_step_triple_refuses_modes_the_builder_cannot_propose(output_mode: str) -> None:
    with pytest.raises(ValidationError):
        StepTriple.model_validate(
            {"input_type": "text", "output_type": "json", "output_mode": output_mode}
        )


def test_planning_state_stamps_the_manifest_version_and_loads_older_stamps() -> None:
    assert FCM_VERSION == 10
    assert PlanningState.empty().fcm_version == 10
    restored = PlanningState.model_validate(
        {**PlanningState.empty().model_dump(mode="json"), "fcm_version": 9}
    )
    assert restored.fcm_version == 9
