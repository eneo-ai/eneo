"""Integrity checks for the AI Builder reliability corpus.

The corpus shares the benchmark case owner so prompts used for discovery
metrics and Flow-shape reliability cannot drift into competing fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.flow_capability_manifest import (
    resolve_capability_for_tuple,
    validate_step_chain,
)
from tests.integration.flows.ai_builder.benchmark.cases import (
    BENCHMARK_CASES,
    RELIABILITY_CORPUS_CASES,
    BehavioralRisk,
    CorpusSource,
    DomainCoupling,
    ExpectedFlowShape,
    ExpectedStepShape,
    ReliabilityCorpusCase,
)

MINIMUM_RELIABILITY_CASES = 7

MANUAL_RUNBOOK_CASE_IDS = frozenset(
    {
        "advanced_audio_meeting_docx_sv",
        "advanced_multi_file_template_docx_sv",
        "advanced_report_pdf_sections_sv",
        "vague_audio_docx_sv",
        "vague_multi_file_docx_sv",
        "vague_report_pdf_sv",
    }
)

INPUT_TYPE_COVERAGE_EXCLUSIONS: dict[FlowInputType, str] = {
    FlowInputType.ANY: "abstract compatibility type, not a user-declared runtime input",
    FlowInputType.FILE: "covered by later mixed-file/input goldens, not the six Swedish prompts",
    FlowInputType.IMAGE: "not exposed to AI Builder as a supported runtime input",
}

OUTPUT_MODE_COVERAGE_EXCLUSIONS: dict[FlowOutputMode, str] = {
    FlowOutputMode.HTTP_POST: "outbound delivery is outside Batch 11 AI Builder proposals",
}


@dataclass(frozen=True, slots=True)
class ChainStepProjection:
    step_order: int
    input_source: FlowInputSource
    input_type: FlowInputType
    output_type: FlowOutputType


def _all_step_shapes() -> tuple[ExpectedStepShape, ...]:
    return tuple(
        step
        for corpus_case in RELIABILITY_CORPUS_CASES
        for step in corpus_case.expected_flow_shape.steps
    )


def _chain_steps(shape: ExpectedFlowShape) -> tuple[ChainStepProjection, ...]:
    return tuple(
        ChainStepProjection(
            step_order=index,
            input_source=step.input_source,
            input_type=step.input_type,
            output_type=step.output_type,
        )
        for index, step in enumerate(shape.steps, start=1)
    )


def _has_slot(corpus_case: ReliabilityCorpusCase, name: str, value: str) -> bool:
    return any(
        slot.name == name and slot.value == value for slot in corpus_case.expected_slots
    )


def _assert_enum_exclusions_are_typed(
    exclusions: dict[FlowInputType, str] | dict[FlowOutputMode, str],
) -> None:
    for rationale in exclusions.values():
        assert rationale.strip()


def test_case_count_and_ids_are_stable() -> None:
    case_ids = [case.case_id for case in RELIABILITY_CORPUS_CASES]
    benchmark_ids = {case.case_id for case in BENCHMARK_CASES}

    assert len(RELIABILITY_CORPUS_CASES) >= MINIMUM_RELIABILITY_CASES
    assert len(case_ids) == len(set(case_ids))
    assert set(case_ids).isdisjoint(benchmark_ids)


def test_manual_runbook_prompts_are_lifted_by_id() -> None:
    manual_case_ids = {
        case.case_id
        for case in RELIABILITY_CORPUS_CASES
        if case.source is CorpusSource.MANUAL_RUNBOOK
    }

    assert manual_case_ids == MANUAL_RUNBOOK_CASE_IDS


def test_cases_are_swedish_with_closed_provenance_tags() -> None:
    assert {case.ui_language for case in RELIABILITY_CORPUS_CASES} == {"sv"}
    assert all(case.prompt.strip() for case in RELIABILITY_CORPUS_CASES)
    assert {case.source for case in RELIABILITY_CORPUS_CASES} <= set(CorpusSource)
    assert {case.domain_coupling for case in RELIABILITY_CORPUS_CASES} <= set(
        DomainCoupling
    )


def test_reported_failure_pins_audio_transcription_step() -> None:
    reported_cases = [
        case
        for case in RELIABILITY_CORPUS_CASES
        if case.source is CorpusSource.REPORTED_FAILURE
    ]

    assert len(reported_cases) == 1
    shape = reported_cases[0].expected_flow_shape
    assert shape.runtime_input is FlowInputType.AUDIO
    assert shape.terminal_output is FlowOutputType.DOCX
    assert any(
        step.input_source is FlowInputSource.FLOW_INPUT
        and step.input_type is FlowInputType.AUDIO
        and step.output_type is FlowOutputType.TEXT
        and step.output_mode is FlowOutputMode.TRANSCRIBE_ONLY
        for step in shape.steps
    )


def test_expected_slots_use_canonical_names() -> None:
    for corpus_case in RELIABILITY_CORPUS_CASES:
        slot_names = [slot.name for slot in corpus_case.expected_slots]
        assert slot_names
        assert len(slot_names) == len(set(slot_names))
        assert set(slot_names) <= KNOWN_REQUIREMENT_SLOT_NAMES
        assert all(slot.value.strip() for slot in corpus_case.expected_slots)


def test_expected_flow_shapes_are_internally_consistent() -> None:
    for corpus_case in RELIABILITY_CORPUS_CASES:
        shape = corpus_case.expected_flow_shape

        assert shape.steps
        assert shape.steps[0].input_source is FlowInputSource.FLOW_INPUT
        assert shape.steps[0].input_type is shape.runtime_input
        assert shape.steps[-1].output_type is shape.terminal_output


def test_expected_step_tuples_are_fcm_legal() -> None:
    for step in _all_step_shapes():
        assert (
            resolve_capability_for_tuple(
                input_source=step.input_source,
                input_type=step.input_type,
                output_type=step.output_type,
                output_mode=step.output_mode,
            )
            is not None
        )


def test_expected_step_chains_are_fcm_legal() -> None:
    for corpus_case in RELIABILITY_CORPUS_CASES:
        assert validate_step_chain(_chain_steps(corpus_case.expected_flow_shape)) == ()


def test_flow_enum_coverage_has_only_explicit_exclusions() -> None:
    observed_input_types = {step.input_type for step in _all_step_shapes()}
    observed_output_types = {step.output_type for step in _all_step_shapes()}
    observed_output_modes = {step.output_mode for step in _all_step_shapes()}

    _assert_enum_exclusions_are_typed(INPUT_TYPE_COVERAGE_EXCLUSIONS)
    _assert_enum_exclusions_are_typed(OUTPUT_MODE_COVERAGE_EXCLUSIONS)

    assert observed_input_types.isdisjoint(INPUT_TYPE_COVERAGE_EXCLUSIONS)
    assert observed_input_types | set(INPUT_TYPE_COVERAGE_EXCLUSIONS) == set(
        FlowInputType
    )
    assert observed_output_types == set(FlowOutputType)
    assert observed_output_modes.isdisjoint(OUTPUT_MODE_COVERAGE_EXCLUSIONS)
    assert observed_output_modes | set(OUTPUT_MODE_COVERAGE_EXCLUSIONS) == set(
        FlowOutputMode
    )


def test_behavioral_risks_have_full_coverage() -> None:
    covered: set[BehavioralRisk] = set()
    for corpus_case in RELIABILITY_CORPUS_CASES:
        assert corpus_case.behavioral_risks
        covered.update(corpus_case.behavioral_risks)

    assert covered == set(BehavioralRisk)


def test_behavioral_risks_match_typed_evidence() -> None:
    for corpus_case in RELIABILITY_CORPUS_CASES:
        steps = corpus_case.expected_flow_shape.steps
        risks = corpus_case.behavioral_risks

        if BehavioralRisk.AUDIO_TRANSCRIPTION in risks:
            assert any(
                step.input_type is FlowInputType.AUDIO
                and step.output_type is FlowOutputType.TEXT
                and step.output_mode is FlowOutputMode.TRANSCRIBE_ONLY
                for step in steps
            )
        if BehavioralRisk.MULTI_DOCUMENT_AGGREGATION in risks:
            assert _has_slot(
                corpus_case,
                "document_material_scope",
                "multiple_documents_case",
            )
        if BehavioralRisk.SECTIONED_REPORT in risks:
            assert corpus_case.expected_flow_shape.terminal_output is FlowOutputType.PDF
            assert _has_slot(
                corpus_case,
                "structured_analysis_need",
                "use_structured_analysis",
            )
        if BehavioralRisk.STRUCTURED_DATA_TO_TEXT in risks:
            assert any(
                step.input_type is FlowInputType.JSON
                and step.output_type is FlowOutputType.TEXT
                for step in steps
            )
        if BehavioralRisk.TEMPLATE_FILL in risks:
            assert any(
                step.output_mode is FlowOutputMode.TEMPLATE_FILL for step in steps
            )


def test_domain_coupling_is_limited_to_reported_failure() -> None:
    coupled_cases = [
        case
        for case in RELIABILITY_CORPUS_CASES
        if case.domain_coupling is not DomainCoupling.NEUTRAL
    ]

    assert len(coupled_cases) <= 1
    assert all(case.source is CorpusSource.REPORTED_FAILURE for case in coupled_cases)
