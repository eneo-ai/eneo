"""Seed goldens for the AI Builder capability matrix.

Each `BuildableGoldenCase` is a real, domain-neutral `FlowDraftSpecCore` the AI
Builder can author. The suite proves every one passes the critic draft preflight
with no architecture blocker, resolves its declared form fields, matches its
declared composition columns. Critic preflight is an early architecture check;
real FlowService materialization through canonical create/edit authoring commands
is the final acceptance fence. LLM-output quality on real planner output belongs
in a committed release or QA runbook, not this deterministic fence.

The set covers every AI-Builder-expressible capability row across the composition
columns, meeting each row's complexity policy and the global coverage thresholds
(every column spans several rows; form-field chains and edit paths clear their
minimum shares). Capabilities the authoring enums cannot express (HTTP) are
recorded as `KnownCapabilityGap`, never faked into a buildable golden.
"""

from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_authoring_spec import (
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
    # Fan-in semantics the critic needs for compare-style flows; comparison
    # goldens set "compare" so the multi-document-compare invariants evaluate
    # the spec the way the planner would.
    aggregation_intent: AggregationIntent = "linear"


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
    input_contract: FlowPersistedJsonObject | None = None,
    output_contract: FlowPersistedJsonObject | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        output_mode=output_mode,
        input_contract=input_contract,
        output_contract=output_contract,
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


def _json_input_to_structured_output_with_contract() -> BuildableGoldenCase:
    input_contract: FlowPersistedJsonObject = {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record_id": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["record_id", "amount"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["records"],
        "additionalProperties": False,
    }
    output_contract: FlowPersistedJsonObject = {
        "type": "object",
        "properties": {
            "normalized_records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record_id": {"type": "string"},
                        "amount": {"type": "number"},
                        "status": {"type": "string"},
                    },
                    "required": ["record_id", "amount"],
                    "additionalProperties": False,
                },
            },
            "totals": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                },
                "required": ["amount", "currency"],
                "additionalProperties": False,
            },
        },
        "required": ["normalized_records", "totals"],
        "additionalProperties": False,
    }
    spec = FlowDraftSpecCore(
        flow_name="Normalisera JSON-underlag",
        steps=[
            _step(
                "step_a",
                "Normalisera JSON",
                "Läs JSON-indatan och returnera normalized_records och totals "
                "enligt det deklarerade kontraktet.",
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
                input_contract=input_contract,
                output_contract=output_contract,
            )
        ],
    )
    return BuildableGoldenCase(
        case_id="json_input_to_structured_output__contract",
        capability_row=CapabilityRow.EXTRACT_STRUCTURED_FIELDS,
        spec=spec,
        declared_columns=frozenset({CompositionColumn.BASIC_SINGLE_STEP}),
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


def _structured_report_basic() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Avtalets risköversikt",
        steps=[
            _step(
                "step_a",
                "Skriv risköversikt",
                "Läs det uppladdade avtalet och skriv en kort risköversikt med de "
                "viktigaste punkterna.",
                input_type=InputType.DOCUMENT,
            )
        ],
    )
    return BuildableGoldenCase(
        case_id="document_to_structured_report__basic",
        capability_row=CapabilityRow.DOCUMENT_TO_STRUCTURED_REPORT,
        spec=spec,
        declared_columns=frozenset({CompositionColumn.BASIC_SINGLE_STEP}),
    )


def _structured_report_advanced() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Fördjupad upphandlingsrapport",
        steps=[
            _step(
                "step_a",
                "Extrahera fynd",
                "Extrahera strukturerade fynd ur upphandlingsdokumentet med fokus "
                "på {{report_focus}}.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_b",
                "Analysera fynd",
                "Analysera och fördjupa resonemanget utifrån "
                "{{step_a.output.structured.findings}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                "step_c",
                "Skriv rapport",
                "Skriv en sammanhållen rapport som väger "
                "{{step_a.output.structured.findings}} mot {{step_b.output.text}} "
                "med fokus på {{report_focus}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
        form_fields=[FormFieldSpec(name="report_focus", type="text", label="Fokus")],
    )
    return BuildableGoldenCase(
        case_id="document_to_structured_report__advanced",
        capability_row=CapabilityRow.DOCUMENT_TO_STRUCTURED_REPORT,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.ADVANCED_MULTI_CAPABILITY,
                CompositionColumn.JSON_IN_JSON_OUT_PIPE,
                CompositionColumn.FORM_FIELDS_CHAIN,
                CompositionColumn.ALL_STEPS_MULTI_REFERENCE,
                CompositionColumn.EDIT_PATH,
            }
        ),
        via_edit=True,
    )


def _pdf_report_basic() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Periodens PDF-rapport",
        steps=[
            _step(
                "step_a",
                "Skapa PDF-rapport",
                "Skapa en PDF-rapport för perioden {{reporting_period}} utifrån "
                "det uppladdade underlaget.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.PDF,
            )
        ],
        form_fields=[
            FormFieldSpec(name="reporting_period", type="text", label="Period")
        ],
    )
    return BuildableGoldenCase(
        case_id="document_to_pdf_report__basic",
        capability_row=CapabilityRow.DOCUMENT_TO_PDF_REPORT,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.BASIC_SINGLE_STEP,
                CompositionColumn.FORM_FIELDS_DECLARE_ONLY,
            }
        ),
    )


def _pdf_report_advanced_edit() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Dokumentanalys till PDF",
        steps=[
            _step(
                "step_a",
                "Extrahera dokumentdata",
                "Extrahera titel, datum, författare, kategori, slutsatser och "
                "sammanfattning ur det uppladdade dokumentet.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_b",
                "Skriv rapporttext",
                "Skriv rapporttexten från {{step_a.output.structured.title}}, "
                "{{step_a.output.structured.category}} och "
                "{{step_a.output.structured.summary}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                "step_c",
                "Skapa PDF",
                "Skapa PDF-filen från {{step_b.output.text}} och stäm av mot "
                "{{step_a.output.structured.conclusions}} med fokus på "
                "{{review_focus}}.",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                output_type=OutputType.PDF,
                output_mode=OutputMode.RENDER_VERBATIM,
            ),
        ],
        form_fields=[FormFieldSpec(name="review_focus", type="text", label="Fokus")],
    )
    return BuildableGoldenCase(
        case_id="document_to_pdf_report__advanced_edit",
        capability_row=CapabilityRow.DOCUMENT_TO_PDF_REPORT,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.ADVANCED_MULTI_CAPABILITY,
                CompositionColumn.ALL_STEPS_MULTI_REFERENCE,
                CompositionColumn.EDIT_PATH,
                CompositionColumn.JSON_IN_JSON_OUT_PIPE,
            }
        ),
        via_edit=True,
    )


def _audio_transcription_basic() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Transkribera intervju",
        steps=[
            _step(
                "step_a",
                "Transkribera ljud",
                "Transkribera den uppladdade intervjuinspelningen till text.",
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            )
        ],
    )
    return BuildableGoldenCase(
        case_id="audio_transcription__basic",
        capability_row=CapabilityRow.AUDIO_TRANSCRIPTION,
        spec=spec,
        declared_columns=frozenset({CompositionColumn.BASIC_SINGLE_STEP}),
    )


def _audio_to_docx_template_advanced() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Transkriberad rapport till DOCX-mall",
        steps=[
            _step(
                "step_a",
                "Transkribera ljud",
                "Transkribera den uppladdade ljudfilen till text.",
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                "step_b",
                "Extrahera avsnitt",
                "Extrahera rapportavsnitt ur {{step_a.output.text}} som JSON.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_c",
                "Skriv rapport",
                "Skriv en sammanhållen rapport från "
                "{{step_b.output.structured.sections}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                "step_d",
                "Fyll DOCX-mall",
                "Fyll DOCX-mallen {{template_name}} med {{step_c.output.text}}.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
            ),
        ],
        form_fields=[FormFieldSpec(name="template_name", type="text", label="Mall")],
    )
    return BuildableGoldenCase(
        case_id="audio_to_docx_template__advanced",
        capability_row=CapabilityRow.AUDIO_TRANSCRIPTION,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.ADVANCED_MULTI_CAPABILITY,
                CompositionColumn.JSON_IN_JSON_OUT_PIPE,
            }
        ),
    )


def _audio_to_structured_text_advanced() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Transkriberade beslut till text",
        steps=[
            _step(
                "step_a",
                "Transkribera ljud",
                "Transkribera den uppladdade ljudfilen till text.",
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                "step_b",
                "Extrahera uppföljning",
                "Extrahera beslut, nästa steg och öppna frågor ur "
                "{{step_a.output.text}} som JSON.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_c",
                "Skriv uppföljningstext",
                "Skriv en strukturerad text som väger originaltranskriptionen "
                "{{step_a.output.text}} mot besluten "
                "{{step_b.output.structured.decisions}}, nästa steg "
                "{{step_b.output.structured.next_steps}} och öppna frågor "
                "{{step_b.output.structured.open_questions}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    return BuildableGoldenCase(
        case_id="audio_to_structured_text__advanced",
        capability_row=CapabilityRow.AUDIO_TRANSCRIPTION,
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


def _comparison_basic() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Jämför offerter",
        steps=[
            _step(
                "step_a",
                "Jämför offerter",
                "Jämför de uppladdade offerterna och returnera en strukturerad "
                "jämförelse i JSON.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
            )
        ],
    )
    return BuildableGoldenCase(
        case_id="comparison__basic",
        capability_row=CapabilityRow.COMPARISON,
        spec=spec,
        declared_columns=frozenset({CompositionColumn.BASIC_SINGLE_STEP}),
        aggregation_intent="compare",
    )


def _comparison_advanced() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Viktad offertjämförelse",
        steps=[
            _step(
                "step_a",
                "Läs offerterna",
                "Extrahera jämförbara nyckeltal ur de uppladdade offerterna "
                "enligt {{criteria}}.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_b",
                "Normalisera nyckeltal",
                "Normalisera nyckeltalen från "
                "{{step_a.output.structured.metrics}} enligt {{criteria}}.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_c",
                "Väg samman",
                "Jämför {{step_a.output.structured.metrics}} och "
                "{{step_b.output.structured.metrics}} mot {{criteria}} och skriv "
                "en motiverad rekommendation.",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
        ],
        form_fields=[FormFieldSpec(name="criteria", type="text", label="Kriterier")],
    )
    return BuildableGoldenCase(
        case_id="comparison__advanced",
        capability_row=CapabilityRow.COMPARISON,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.ADVANCED_MULTI_CAPABILITY,
                CompositionColumn.JSON_IN_JSON_OUT_PIPE,
                CompositionColumn.FORM_FIELDS_CHAIN,
                CompositionColumn.ALL_STEPS_MULTI_REFERENCE,
            }
        ),
        aggregation_intent="compare",
    )


def _docx_template_advanced() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Mallfyllning med granskning",
        steps=[
            _step(
                "step_a",
                "Extrahera variabler",
                "Extrahera mallvariabler ur det uppladdade dokumentet för "
                "{{template_name}}.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_b",
                "Validera variabler",
                "Komplettera och validera variablerna från "
                "{{step_a.output.structured.fields}}.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_c",
                "Fyll mallen",
                "Fyll DOCX-mallen {{template_name}} med variablerna från "
                "{{step_b.output.structured.fields}}.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
            ),
        ],
        form_fields=[FormFieldSpec(name="template_name", type="text", label="Mall")],
    )
    return BuildableGoldenCase(
        case_id="document_to_docx_template__advanced",
        capability_row=CapabilityRow.DOCUMENT_TO_DOCX_TEMPLATE,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.ADVANCED_MULTI_CAPABILITY,
                CompositionColumn.JSON_IN_JSON_OUT_PIPE,
                CompositionColumn.FORM_FIELDS_CHAIN,
                CompositionColumn.EDIT_PATH,
            }
        ),
        via_edit=True,
    )


def _sectioned_form_intake_basic() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Enkel introduktionsplan",
        steps=[
            _step(
                "step_a",
                "Sammanställ plan",
                "Sammanställ en introduktionsplan för {{applicant_name}} i rollen "
                "{{role}}.",
            )
        ],
        form_fields=[
            FormFieldSpec(name="applicant_name", type="text", label="Namn"),
            FormFieldSpec(name="role", type="text", label="Roll"),
        ],
    )
    return BuildableGoldenCase(
        case_id="sectioned_form_intake__basic",
        capability_row=CapabilityRow.SECTIONED_FORM_INTAKE,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.BASIC_SINGLE_STEP,
                CompositionColumn.FORM_FIELDS_DECLARE_ONLY,
            }
        ),
    )


def _sectioned_form_intake_advanced() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Avsnittsintag med underlag",
        steps=[
            _step(
                "step_a",
                "Extrahera avsnitt",
                "Extrahera relevanta avsnitt ur det uppladdade underlaget för "
                "{{unit}}.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_b",
                "Skriv utkast",
                "Skriv ett utkast utifrån {{step_a.output.structured.sections}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                "step_c",
                "Färdigställ",
                "Färdigställ texten från {{step_b.output.text}} med fokus på {{unit}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
        form_fields=[FormFieldSpec(name="unit", type="text", label="Enhet")],
    )
    return BuildableGoldenCase(
        case_id="sectioned_form_intake__advanced",
        capability_row=CapabilityRow.SECTIONED_FORM_INTAKE,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.ADVANCED_MULTI_CAPABILITY,
                CompositionColumn.JSON_IN_JSON_OUT_PIPE,
                CompositionColumn.FORM_FIELDS_CHAIN,
            }
        ),
    )


def _form_intake_to_docx_template_advanced() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Formulär till DOCX-mall",
        steps=[
            _step(
                "step_a",
                "Sammanställ formulär",
                "Sammanställ avsnitt från {{applicant_name}}, {{case_type}} "
                "och {{decision_goal}}.",
            ),
            _step(
                "step_b",
                "Skriv sluttext",
                "Skriv en slutlig text från {{step_a.output.text}} med målet "
                "{{decision_goal}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                "step_c",
                "Fyll DOCX-mall",
                "Fyll DOCX-mallen {{template_name}} med {{step_b.output.text}}.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
            ),
        ],
        form_fields=[
            FormFieldSpec(name="applicant_name", type="text", label="Namn"),
            FormFieldSpec(name="case_type", type="text", label="Typ"),
            FormFieldSpec(name="decision_goal", type="text", label="Mål"),
            FormFieldSpec(name="template_name", type="text", label="Mall"),
        ],
    )
    return BuildableGoldenCase(
        case_id="form_intake_to_docx_template__advanced",
        capability_row=CapabilityRow.DOCUMENT_TO_DOCX_TEMPLATE,
        spec=spec,
        declared_columns=frozenset(
            {
                CompositionColumn.ADVANCED_MULTI_CAPABILITY,
                CompositionColumn.FORM_FIELDS_CHAIN,
            }
        ),
    )


def _underlag_till_text_pipe() -> BuildableGoldenCase:
    spec = FlowDraftSpecCore(
        flow_name="Strukturerad data till text",
        steps=[
            _step(
                "step_a",
                "Extrahera data",
                "Extrahera strukturerade uppgifter ur det uppladdade formuläret.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
            ),
            _step(
                "step_b",
                "Skriv text",
                "Skriv en sammanhängande text utifrån "
                "{{step_a.output.structured.data}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    return BuildableGoldenCase(
        case_id="underlag_till_text__pipe",
        capability_row=CapabilityRow.UNDERLAG_TILL_TEXT,
        spec=spec,
        declared_columns=frozenset({CompositionColumn.JSON_IN_JSON_OUT_PIPE}),
    )


GOLDEN_CASES: tuple[BuildableGoldenCase, ...] = (
    _summarize_text(),
    _extract_structured_fields(),
    _json_input_to_structured_output_with_contract(),
    _sectioned_form_intake(),
    _document_to_docx_template(),
    _document_to_docx_create(),
    _structured_report_basic(),
    _structured_report_advanced(),
    _pdf_report_basic(),
    _pdf_report_advanced_edit(),
    _audio_transcription_basic(),
    _audio_to_docx_template_advanced(),
    _audio_to_structured_text_advanced(),
    _comparison_basic(),
    _comparison_advanced(),
    _docx_template_advanced(),
    _sectioned_form_intake_basic(),
    _sectioned_form_intake_advanced(),
    _form_intake_to_docx_template_advanced(),
    _underlag_till_text_pipe(),
)


KNOWN_GAPS: tuple[KnownCapabilityGap, ...] = (
    KnownCapabilityGap(
        capability_row=CapabilityRow.HTTP_POST_CALL,
        runtime_input_sources=frozenset(),
        runtime_output_modes=frozenset({FlowOutputMode.HTTP_POST}),
        why_not_authorable=(
            "FlowAuthoringOutputMode omits http_post, so a FlowDraftSpecCore step "
            "cannot be authored with an outbound HTTP POST call."
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
            "FlowAuthoringInputSource omits http_get, so a FlowDraftSpecCore step "
            "cannot be authored that fetches input over HTTP GET."
        ),
        product_decision=(
            "Decide whether the AI Builder should author inbound HTTP GET steps "
            "before this row can hold a buildable golden."
        ),
    ),
)
