from __future__ import annotations

import json
from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_api_models import SessionTelemetrySummary
from eneo.flows.ai_builder.ai_builder_domain_models import FlowBuilderProposalContent
from eneo.flows.ai_builder.ai_builder_event_models import (
    KeyDecisionPayload,
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_done_event,
    build_plan_event,
    build_question_event,
    build_requirements_summary_event,
    build_usage_event,
    encode_ai_builder_stream_event,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


def test_done_event_preserves_empty_data_frame() -> None:
    assert encode_ai_builder_stream_event(build_done_event()) == {
        "event": "done",
        "data": "",
    }


def test_usage_event_serializes_typed_telemetry() -> None:
    telemetry = SessionTelemetrySummary(
        planner_request_count=1,
        prompt_tokens_total=120,
        completion_tokens_total=30,
        total_tokens_total=150,
        last_request_id="request-1",
        last_model="gpt-5.4",
    )

    event = encode_ai_builder_stream_event(build_usage_event(telemetry))

    assert event["event"] == "usage"
    data = json.loads(event["data"])
    assert data["planner_request_count"] == 1
    assert data["total_tokens_total"] == 150
    assert data["last_request_id"] == "request-1"
    assert data["last_model"] == "gpt-5.4"


def test_plan_event_serializes_derived_execution_shape() -> None:
    proposal = FlowBuilderProposalContent(
        spec=FlowDraftSpecCore(
            flow_name="Summarize",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Summarize",
                    assistant_spec=AssistantSpec(instructions="Summarize the input."),
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                )
            ],
        )
    )

    event = encode_ai_builder_stream_event(
        build_plan_event(plan_id=uuid4(), proposal=proposal)
    )

    assert json.loads(event["data"])["proposal"]["execution_shape"] == {
        "completion_model_step_count": 1,
        "transcription_model_step_count": 0,
        "deterministic_step_count": 0,
        "schema_constrained_step_count": 0,
        "mapped_step_upper_bounds": [],
    }


def test_question_event_serializes_typed_payload_without_none_options() -> None:
    question = StructuredQuestionPayload.model_validate(
        {
            "question_id": "runtime_metadata_fields",
            "question": "Vilka fält behöver vi?",
            "options": [
                {"value": "title", "label": "Rubrik", "description": None},
                {"value": "author", "label": "Författare", "description": None},
            ],
            "selection_mode": "multi",
            "allow_custom": False,
        }
    )

    event = encode_ai_builder_stream_event(build_question_event(question))

    assert event["event"] == "question"
    assert json.loads(event["data"]) == {
        "question_id": "runtime_metadata_fields",
        "question": "Vilka fält behöver vi?",
        "options": [
            {"label": "Rubrik", "value": "title"},
            {"label": "Författare", "value": "author"},
        ],
        "selection_mode": "multi",
        "allow_custom": False,
        "requires_confirm": False,
    }


def test_requirements_summary_event_serializes_typed_payload() -> None:
    payload = RequirementsSummaryPayload(
        requirements_version="requirements-v1",
        summary="Create a meeting report from audio.",
        key_decisions=[KeyDecisionPayload(topic="Input", decision="Meeting audio")],
        input_description="One audio file per run.",
        output_description="DOCX meeting report.",
    )

    event = encode_ai_builder_stream_event(build_requirements_summary_event(payload))

    assert event["event"] == "requirements_summary"
    assert json.loads(event["data"]) == {
        "requirements_version": "requirements-v1",
        "summary": "Create a meeting report from audio.",
        "key_decisions": [{"topic": "Input", "decision": "Meeting audio"}],
        "input_description": "One audio file per run.",
        "output_description": "DOCX meeting report.",
        "assumptions": [],
        "manual_setup_notes": [],
    }
