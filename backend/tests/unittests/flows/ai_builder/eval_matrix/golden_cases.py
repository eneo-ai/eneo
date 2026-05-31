"""Seed goldens for the AI Builder capability matrix.

Each `BuildableGoldenCase` is a real, domain-neutral `FlowDraftSpecCore` the AI
Builder can author. The suite proves every one passes the critic draft preflight
with no architecture blocker, resolves its declared form fields, and that its
declared composition columns match what the spec shape derives. End-to-end
materialization is the live-eval runner's job, not this deterministic fence.

This is the foundation set: enough goldens to exercise the column-derivation and
ratchet machinery across distinct shapes. Growing to full per-row and per-column
coverage (and switching on the population thresholds) is the next step; the
matrix-state ratchet in `taxonomy.py` keeps the not-yet-seeded rows visible.

Capabilities the authoring enums cannot express (HTTP) are recorded as
`KnownCapabilityGap`, never faked into a buildable golden.
"""

from __future__ import annotations

from dataclasses import dataclass

from intric.flows.enums import FlowInputSource, FlowOutputMode
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)

from .taxonomy import CapabilityRow, CompositionColumn


@dataclass(frozen=True)
class BuildableGoldenCase:
    case_id: str
    capability_row: CapabilityRow
    spec: FlowDraftSpecCore
    declared_columns: frozenset[CompositionColumn]
    via_edit: bool = False


@dataclass(frozen=True)
class KnownCapabilityGap:
    capability_row: CapabilityRow
    # Typed proof the runtime supports this shape: real Flow enum members the
    # AI Builder authoring enums omit. The suite asserts these are absent from
    # the builder enums, so a gap cannot quietly claim support that vanished.
    runtime_input_sources: frozenset[FlowInputSource]
    runtime_output_modes: frozenset[FlowOutputMode]
    why_not_authorable: str
    product_decision: str


def _step(
    ref: str,
    name: str,
    instructions: str,
    *,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        output_mode=output_mode,
    )


def _summarize_text() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Sammanfatta mötesanteckningar",
        steps=[
            _step(
                "step_a",
                "Sammanfatta anteckningar",
                "Sammanfatta de inklistrade anteckningarna till tydliga punkter.",
            )
        ],
    )
    return BuildableGoldenCase(
        case_id="summarize_text__basic",
        capability_row=CapabilityRow.SUMMARIZE_TEXT,
        spec=spec,
        declared_columns=frozenset({CompositionColumn.BASIC_SINGLE_STEP}),
    )


def _extract_structured_fields() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Extrahera kunduppgifter",
        steps=[
            _step(
                "step_a",
                "Extrahera fält",
                "Extrahera uppgifter för {{customer_name}} med fokus på "
                "{{focus_area}} och returnera strukturerad JSON.",
                output_type=OutputType.JSON,
            )
        ],
        form_fields=[
            FormFieldSpec(name="customer_name", type="text", label="Kundnamn"),
            FormFieldSpec(name="focus_area", type="text", label="Fokusområde"),
        ],
    )
    return BuildableGoldenCase(
        case_id="extract_structured_fields__form_fields_declare_only",
        capability_row=CapabilityRow.EXTRACT_STRUCTURED_FIELDS,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.BASIC_SINGLE_STEP,
                CompositionColumn.FORM_FIELDS_DECLARE_ONLY,
            }
        ),
    )


def _sectioned_form_intake() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Strukturerad inmatning i avsnitt",
        steps=[
            _step(
                "step_a",
                "Samla in avsnitt",
                "Sammanställ underlag från {{background}} och {{goal}}.",
            ),
            _step(
                "step_b",
                "Utveckla avsnitt",
                "Utveckla resonemanget utifrån {{step_a.output.text}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                "step_c",
                "Färdigställ text",
                "Skriv en slutlig text från {{step_b.output.text}} med hänsyn "
                "till {{background}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
        form_fields=[
            FormFieldSpec(name="background", type="text", label="Bakgrund"),
            FormFieldSpec(name="goal", type="text", label="Mål"),
        ],
    )
    return BuildableGoldenCase(
        case_id="sectioned_form_intake__form_fields_chain",
        capability_row=CapabilityRow.SECTIONED_FORM_INTAKE,
        spec=spec,
        declared_columns=frozenset({CompositionColumn.FORM_FIELDS_CHAIN}),
    )


def _document_to_docx_template() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Fyll DOCX-mall",
        steps=[
            _step(
                "step_a",
                "Fyll mallen",
                "Fyll i den uppladdade DOCX-mallens platshållare utifrån dokumentet.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
            )
        ],
    )
    return BuildableGoldenCase(
        case_id="document_to_docx_template__fill",
        capability_row=CapabilityRow.DOCUMENT_TO_DOCX_TEMPLATE,
        spec=spec,
        declared_columns=frozenset({CompositionColumn.BASIC_SINGLE_STEP}),
    )


def _document_to_docx_create() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Skapa DOCX-rapport",
        steps=[
            _step(
                "step_a",
                "Skapa rapport",
                "Skapa ett nytt DOCX-dokument som sammanfattar det uppladdade "
                "dokumentet.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.DOCX,
            )
        ],
    )
    return BuildableGoldenCase(
        case_id="document_to_docx_create__basic",
        capability_row=CapabilityRow.DOCUMENT_TO_DOCX_CREATE,
        spec=spec,
        declared_columns=frozenset({CompositionColumn.BASIC_SINGLE_STEP}),
    )


def _multi_step_quality_chain() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Granskningskedja",
        steps=[
            _step(
                "step_a",
                "Extrahera underlag",
                "Extrahera strukturerade fynd från det uppladdade dokumentet.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_b",
                "Analysera kvalitet",
                "Granska och förbättra resonemanget utifrån "
                "{{step_a.output.structured.findings}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                "step_c",
                "Skapa slutrapport",
                "Skapa ett DOCX-dokument från {{step_b.output.text}}.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )
    return BuildableGoldenCase(
        case_id="multi_step_quality_chain__advanced_edit",
        capability_row=CapabilityRow.MULTI_STEP_QUALITY_CHAIN,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.ADVANCED_MULTI_CAPABILITY,
                CompositionColumn.JSON_IN_JSON_OUT_PIPE,
                CompositionColumn.EDIT_PATH,
            }
        ),
        via_edit=True,
    )


GOLDEN_CASES: tuple[BuildableGoldenCase, ...] = (
    _summarize_text(),
    _extract_structured_fields(),
    _sectioned_form_intake(),
    _document_to_docx_template(),
    _document_to_docx_create(),
    _multi_step_quality_chain(),
)


KNOWN_GAPS: tuple[KnownCapabilityGap, ...] = (
    KnownCapabilityGap(
        capability_row=CapabilityRow.HTTP_POST_CALL,
        runtime_input_sources=frozenset({FlowInputSource.HTTP_POST}),
        runtime_output_modes=frozenset({FlowOutputMode.HTTP_POST}),
        why_not_authorable=(
            "AIBuilderOutputMode and AIBuilderInputSource omit http_post, so a "
            "FlowDraftSpecCore step cannot be authored with an HTTP POST call."
        ),
        product_decision=(
            "Decide whether the AI Builder should author outbound HTTP steps "
            "before this row can hold a buildable golden."
        ),
    ),
    KnownCapabilityGap(
        capability_row=CapabilityRow.HTTP_GET_CALL,
        runtime_input_sources=frozenset({FlowInputSource.HTTP_GET}),
        runtime_output_modes=frozenset(),
        why_not_authorable=(
            "AIBuilderInputSource omits http_get, so a FlowDraftSpecCore step "
            "cannot be authored that fetches input over HTTP GET."
        ),
        product_decision=(
            "Decide whether the AI Builder should author inbound HTTP GET steps "
            "before this row can hold a buildable golden."
        ),
    ),
)
