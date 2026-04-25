"""Golden offline quality cases for AI Builder planner drafts."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_validator import validate_spec


class TestAIBuilderGoldenCases:
    def test_json_extraction_pipeline_is_valid(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Kommunanalys",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Extrahera fakta",
                    assistant_spec=AssistantSpec(
                        instructions=(
                            "Extrahera titel, sammanfattning och risk från dokumentet. "
                            "Svara strikt i JSON enligt kontraktet."
                        )
                    ),
                    input_source="flow_input",
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {
                            "titel": {"type": "string", "description": "Kort rubrik"},
                            "sammanfattning": {
                                "type": "string",
                                "description": "Kort sammanfattning",
                            },
                            "risk": {"type": "string", "description": "Risknivå"},
                        },
                    },
                ),
                StepSpec(
                    plan_step_ref="step_b",
                    name="Skriv beslutsunderlag",
                    assistant_spec=AssistantSpec(
                        instructions=(
                            "Skriv ett kort beslutsunderlag på svenska baserat på de extraherade fälten. "
                            "Var tydlig, saklig och använd hela meningar."
                        )
                    ),
                    input_source="previous_step",
                    input_type="json",
                    input_bindings={
                        "question": (
                            "Titel: {{ step_1.output.structured.titel }}\n"
                            "Sammanfattning: {{ step_1.output.structured.sammanfattning }}\n"
                            "Risk: {{ step_1.output.structured.risk }}"
                        )
                    },
                ),
            ],
        )

        validation = validate_spec(spec)
        assert validation.valid is True
        assert validation.warnings == []

    def test_form_driven_summary_flow_is_valid(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Sammanfatta ärende",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Formulera sammanfattning",
                    assistant_spec=AssistantSpec(
                        instructions=(
                            "Skriv en kort ärendesammanfattning baserat på bakgrund, mål och prioritet. "
                            "Lyft fram det som påverkar beslutet mest."
                        )
                    ),
                    input_source="flow_input",
                    input_bindings={
                        "question": (
                            "Bakgrund: {{ Bakgrund }}\n"
                            "Mål: {{ Mål }}\n"
                            "Prioritet: {{ Prioritet }}"
                        )
                    },
                )
            ],
            form_fields=[
                FormFieldSpec(
                    name="Bakgrund", type="text", label="Bakgrund", required=True
                ),
                FormFieldSpec(name="Mål", type="text", label="Mål", required=True),
                FormFieldSpec(
                    name="Prioritet",
                    type="select",
                    label="Prioritet",
                    options=["Hög", "Medel", "Låg"],
                ),
            ],
        )

        validation = validate_spec(spec)
        assert validation.valid is True

    def test_template_fill_flow_is_valid(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Fyll rapportmall",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Extrahera nyckeldata",
                    assistant_spec=AssistantSpec(
                        instructions=(
                            "Extrahera projektnamn, ägare och slutsats i JSON-format. "
                            "Fälten ska kunna användas direkt i en rapportmall."
                        )
                    ),
                    input_source="flow_input",
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {
                            "projektnamn": {
                                "type": "string",
                                "description": "Projektets namn",
                            },
                            "agare": {
                                "type": "string",
                                "description": "Ansvarig ägare",
                            },
                            "slutsats": {
                                "type": "string",
                                "description": "Kort slutsats",
                            },
                        },
                    },
                ),
                StepSpec(
                    plan_step_ref="step_b",
                    name="Fyll DOCX-mall",
                    assistant_spec=AssistantSpec(
                        instructions=(
                            "Fyll i DOCX-mallen med de extraherade fälten. "
                            "Bevara mallens disposition och ersätt endast bindningarna."
                        )
                    ),
                    input_source="previous_step",
                    input_type="json",
                    output_mode="template_fill",
                    output_type="docx",
                    input_bindings={
                        "question": (
                            "Projektnamn: {{ step_1.output.structured.projektnamn }}\n"
                            "Ägare: {{ step_1.output.structured.agare }}\n"
                            "Slutsats: {{ step_1.output.structured.slutsats }}"
                        )
                    },
                    output_config={
                        "bindings": {
                            "projektnamn": "{{ step_1.output.structured.projektnamn }}",
                            "agare": "{{ step_1.output.structured.agare }}",
                            "slutsats": "{{ step_1.output.structured.slutsats }}",
                        }
                    },
                ),
            ],
        )

        validation = validate_spec(spec)
        assert validation.valid is True
