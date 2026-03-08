"""TDD tests for typed I/O publish-time validation in FlowService — RED phase."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.flow import FlowStep
from intric.flows.flow_service import FlowService
from intric.main.exceptions import BadRequestException


def _step(
    step_order: int = 1,
    *,
    input_source: str = "flow_input",
    input_type: str = "text",
    input_contract: dict | None = None,
    input_config: dict | None = None,
    output_mode: str = "pass_through",
    output_type: str = "text",
    output_contract: dict | None = None,
    output_config: dict | None = None,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        # Keep deterministic unique names per step so publish-time
        # uniqueness validation doesn't fail unrelated typed I/O tests.
        user_description=f"Step {step_order}",
        input_source=input_source,
        input_type=input_type,
        input_contract=input_contract,
        input_config=input_config,
        output_mode=output_mode,
        output_type=output_type,
        output_contract=output_contract,
        output_config=output_config,
        mcp_policy="inherit",
    )


def _service(user) -> FlowService:
    service = FlowService(
        user=user,
        flow_repo=AsyncMock(),
        flow_version_repo=AsyncMock(),
        assistant_service=AsyncMock(),
        file_repo=AsyncMock(),
    )
    service._validate_assistant_scope_for_steps = AsyncMock()
    return service


# --- Schema syntax validation ---


def test_rejects_invalid_input_contract(user):
    """Invalid JSON Schema in input_contract should be rejected at publish time."""
    service = _service(user)
    steps = [_step(input_contract={"type": "not_a_type"})]
    with pytest.raises(BadRequestException, match="not a valid JSON Schema"):
        service._validate_steps(steps)


def test_rejects_invalid_output_contract(user):
    """Invalid JSON Schema in output_contract should be rejected."""
    service = _service(user)
    steps = [_step(output_contract={"type": "not_a_type"})]
    with pytest.raises(BadRequestException, match="not a valid JSON Schema"):
        service._validate_steps(steps)


def test_rejects_output_contract_for_text_output(user):
    service = _service(user)
    steps = [_step(output_type="text", output_contract={"type": "object"})]
    with pytest.raises(BadRequestException, match="output_contract is not supported for output_type 'text'"):
        service._validate_steps(steps)


@pytest.mark.parametrize("output_type", ["pdf", "docx"])
def test_rejects_document_output_contract_with_scalar_schema(user, output_type: str):
    service = _service(user)
    steps = [_step(output_type=output_type, output_contract={"type": "string"})]
    with pytest.raises(BadRequestException, match="must declare schema type 'object' or 'array'"):
        service._validate_steps(steps)


@pytest.mark.parametrize("output_type", ["pdf", "docx"])
def test_accepts_document_output_contract_with_structured_schema(user, output_type: str):
    service = _service(user)
    steps = [
        _step(
            output_type=output_type,
            output_contract={"type": "object", "properties": {"title": {"type": "string"}}},
        )
    ]
    service._validate_steps(steps)


def test_accepts_valid_contracts(user):
    """Valid contracts should pass validation."""
    service = _service(user)
    steps = [
        _step(
            input_contract={"type": "object", "properties": {"name": {"type": "string"}}},
            output_type="json",
            output_contract={"type": "object", "required": ["result"]},
        )
    ]
    service._validate_steps(steps)  # should not raise


# --- Type chain compatibility ---


def test_rejects_incompatible_chain(user):
    """pdf output -> audio input should be rejected."""
    service = _service(user)
    steps = [
        _step(step_order=1, output_type="pdf"),
        _step(step_order=2, input_source="previous_step", input_type="audio"),
    ]
    with pytest.raises(BadRequestException):
        service._validate_steps(steps)


def test_accepts_compatible_chain(user):
    """json output -> text input should be accepted."""
    service = _service(user)
    steps = [
        _step(step_order=1, output_type="json"),
        _step(step_order=2, input_source="previous_step", input_type="text"),
    ]
    service._validate_steps(steps)  # should not raise


@pytest.mark.parametrize(
    ("previous_output_type", "current_input_type"),
    [
        ("text", "json"),
        ("json", "json"),
        ("text", "any"),
        ("json", "any"),
        ("pdf", "any"),
        ("docx", "any"),
    ],
)
def test_accepts_previous_step_compatible_coercions_matrix(
    user,
    previous_output_type: str,
    current_input_type: str,
):
    """Allowed previous_step coercions should pass publish validation."""
    service = _service(user)
    steps = [
        _step(step_order=1, output_type=previous_output_type),
        _step(step_order=2, input_source="previous_step", input_type=current_input_type),
    ]
    service._validate_steps(steps)


@pytest.mark.parametrize(
    ("previous_output_type", "current_input_type"),
    [
        ("docx", "json"),
        ("pdf", "json"),
    ],
)
def test_rejects_previous_step_incompatible_coercions_matrix(
    user,
    previous_output_type: str,
    current_input_type: str,
):
    """Unsupported previous_step coercions should fail with deterministic chain error."""
    service = _service(user)
    steps = [
        _step(step_order=1, output_type=previous_output_type),
        _step(step_order=2, input_source="previous_step", input_type=current_input_type),
    ]
    with pytest.raises(BadRequestException, match="incompatible type chain"):
        service._validate_steps(steps)


def test_accepts_five_step_mixed_chain(user):
    """Five-step mixed chain should validate when each previous_step coercion is compatible."""
    service = _service(user)
    steps = [
        _step(step_order=1, input_source="flow_input", input_type="text", output_type="json"),
        _step(step_order=2, input_source="previous_step", input_type="text", output_type="pdf"),
        _step(step_order=3, input_source="previous_step", input_type="text", output_type="docx"),
        _step(step_order=4, input_source="previous_step", input_type="text", output_type="text"),
        _step(step_order=5, input_source="all_previous_steps", input_type="text", output_type="text"),
    ]
    service._validate_steps(steps)  # should not raise


def test_rejects_five_step_mixed_chain_with_incompatible_hop(user):
    """A later incompatible previous_step hop should still be rejected deterministically."""
    service = _service(user)
    steps = [
        _step(step_order=1, input_source="flow_input", input_type="text", output_type="json"),
        _step(step_order=2, input_source="previous_step", input_type="text", output_type="pdf"),
        _step(step_order=3, input_source="previous_step", input_type="json", output_type="text"),
    ]
    with pytest.raises(BadRequestException, match="incompatible type chain"):
        service._validate_steps(steps)


# --- Block all_previous_steps + json ---


def test_all_previous_steps_json_blocked(user):
    """all_previous_steps + input_type=json should be blocked at publish."""
    service = _service(user)
    steps = [
        _step(step_order=1),
        _step(step_order=2, input_source="all_previous_steps", input_type="json"),
    ]
    with pytest.raises(BadRequestException, match="incompatible with input_source 'all_previous_steps'"):
        service._validate_steps(steps)


def test_rejects_first_step_all_previous_steps_input_source_publish(user):
    """Step 1 must not use all_previous_steps."""
    service = _service(user)
    steps = [_step(step_order=1, input_source="all_previous_steps", input_type="text")]
    with pytest.raises(BadRequestException, match="Step 1 cannot use previous_step/all_previous_steps input source"):
        service._validate_steps(steps)


# --- Block document input on non-flow_input sources ---


def test_previous_step_document_blocked(user):
    """previous_step + input_type=document should be rejected at publish."""
    service = _service(user)
    steps = [
        _step(step_order=1, output_type="pdf"),
        _step(step_order=2, input_source="previous_step", input_type="document"),
    ]
    with pytest.raises(BadRequestException, match="input_type 'document' is only supported with input_source 'flow_input'"):
        service._validate_steps(steps)


def test_all_previous_steps_document_blocked(user):
    """all_previous_steps + input_type=document should be rejected at publish."""
    service = _service(user)
    steps = [
        _step(step_order=1),
        _step(step_order=2, input_source="all_previous_steps", input_type="document"),
    ]
    with pytest.raises(BadRequestException, match="input_type 'document' is only supported with input_source 'flow_input'"):
        service._validate_steps(steps)


def test_file_input_source_must_be_flow_input(user):
    """file input type should be rejected when source is previous_step."""
    service = _service(user)
    steps = [
        _step(step_order=1, output_type="text"),
        _step(step_order=2, input_source="previous_step", input_type="file"),
    ]
    with pytest.raises(BadRequestException, match="input_type 'file' is only supported with input_source 'flow_input'"):
        service._validate_steps(steps)


def test_rejects_multiple_flow_input_steps(user):
    """Only one flow_input step is allowed."""
    service = _service(user)
    steps = [
        _step(step_order=1, input_source="flow_input", input_type="text"),
        _step(step_order=2, input_source="flow_input", input_type="text"),
    ]
    with pytest.raises(BadRequestException, match="Only one step may use input_source 'flow_input'"):
        service._validate_steps(steps)


def test_rejects_flow_input_when_not_step_one(user):
    """flow_input is optional, but must be step 1 when present."""
    service = _service(user)
    steps = [
        _step(
            step_order=1,
            input_source="http_get",
            input_type="text",
            input_config={"url": "https://example.org/input"},
        ),
        _step(step_order=2, input_source="flow_input", input_type="text"),
    ]
    with pytest.raises(BadRequestException, match="input_source 'flow_input' must be step 1 if present"):
        service._validate_steps(steps)


def test_allows_http_only_flow_without_flow_input(user):
    """Zero-flow_input flows remain valid."""
    service = _service(user)
    steps = [
        _step(
            step_order=1,
            input_source="http_get",
            input_type="text",
            input_config={"url": "https://example.org/input"},
        ),
        _step(
            step_order=2,
            input_source="http_post",
            input_type="text",
            input_config={"url": "https://example.org/input"},
        ),
    ]

    service._validate_steps(steps)


# --- Audio/Image input type validation ---


def test_audio_input_requires_transcription_enabled(user):
    """audio input requires wizard transcription_enabled=true."""
    service = _service(user)
    steps = [_step(input_type="audio")]
    metadata = {
        "wizard": {
            "transcription_enabled": False,
            "transcription_model": {"id": str(uuid4())},
            "transcription_language": "sv",
        }
    }
    with pytest.raises(BadRequestException, match="Transcription must be enabled"):
        service._validate_steps(steps, metadata_json=metadata)


def test_audio_input_requires_transcription_model(user):
    """audio input requires wizard transcription model selection."""
    service = _service(user)
    steps = [_step(input_type="audio")]
    metadata = {
        "wizard": {
            "transcription_enabled": True,
            "transcription_language": "sv",
        }
    }
    with pytest.raises(BadRequestException, match="transcription model must be selected"):
        service._validate_steps(steps, metadata_json=metadata)


def test_audio_input_accepts_valid_transcription_config(user):
    """audio input should pass publish validation with valid transcription wizard config."""
    service = _service(user)
    steps = [_step(input_type="audio", input_source="flow_input")]
    metadata = {
        "wizard": {
            "transcription_enabled": True,
            "transcription_model": {"id": str(uuid4())},
            "transcription_language": "sv",
        }
    }
    service._validate_steps(steps, metadata_json=metadata)


def test_audio_input_source_must_be_flow_input(user):
    """audio input type should be rejected when source is previous_step."""
    service = _service(user)
    steps = [
        _step(step_order=1, output_type="text"),
        _step(step_order=2, input_source="previous_step", input_type="audio"),
    ]
    metadata = {
        "wizard": {
            "transcription_enabled": True,
            "transcription_model": {"id": str(uuid4())},
            "transcription_language": "sv",
        }
    }
    with pytest.raises(BadRequestException, match="input_type 'audio' is only supported with input_source 'flow_input'"):
        service._validate_steps(steps, metadata_json=metadata)


def test_transcribe_only_requires_audio_input(user):
    """transcribe_only mode is only valid for audio input steps."""
    service = _service(user)
    steps = [
        _step(input_type="text", output_mode="transcribe_only", output_type="text"),
    ]
    with pytest.raises(BadRequestException, match="transcribe_only.*input_type 'audio'"):
        service._validate_steps(steps)


def test_transcribe_only_requires_text_output(user):
    """transcribe_only mode is only valid for text output."""
    service = _service(user)
    steps = [
        _step(input_type="audio", output_mode="transcribe_only", output_type="docx"),
    ]
    metadata = {
        "wizard": {
            "transcription_enabled": True,
            "transcription_model": {"id": str(uuid4())},
            "transcription_language": "sv",
        }
    }
    with pytest.raises(BadRequestException, match="transcribe_only.*output_type 'text'"):
        service._validate_steps(steps, metadata_json=metadata)


def test_transcribe_only_accepts_audio_text_combination(user):
    """transcribe_only should be accepted for audio -> text steps."""
    service = _service(user)
    steps = [
        _step(input_type="audio", output_mode="transcribe_only", output_type="text"),
    ]
    metadata = {
        "wizard": {
            "transcription_enabled": True,
            "transcription_model": {"id": str(uuid4())},
            "transcription_language": "sv",
        }
    }
    service._validate_steps(steps, metadata_json=metadata)


def test_image_input_blocked_publish(user):
    """image input type should be blocked at publish."""
    service = _service(user)
    steps = [_step(input_type="image")]
    with pytest.raises(BadRequestException, match="image is not yet supported"):
        service._validate_steps(steps)


# --- Block input_contract on non-text/json ---


def test_input_contract_on_document_blocked(user):
    """input_contract on document input should be blocked at publish."""
    service = _service(user)
    steps = [_step(input_type="document", input_contract={"type": "object"})]
    with pytest.raises(BadRequestException, match="input_contract is not supported"):
        service._validate_steps(steps)


def test_input_contract_on_text_allowed(user):
    """input_contract on text input should be allowed."""
    service = _service(user)
    steps = [_step(input_type="text", input_contract={"type": "string"})]
    service._validate_steps(steps)  # should not raise


def test_input_contract_on_json_allowed(user):
    """input_contract on json input should be allowed."""
    service = _service(user)
    steps = [_step(input_type="json", input_contract={"type": "object"})]
    service._validate_steps(steps)  # should not raise
