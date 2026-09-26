from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.runtime import RuntimeStep, StepDiagnostic, StepExecutionOutput
from eneo.flows.runtime.execution_state_builder import build_run_execution_state
from eneo.flows.runtime.step_result_builder import (
    build_completed_step_result,
    build_default_failed_input_payload,
    build_failed_step_result,
    build_transcribe_only_rag_metadata,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.parametrize(
    "prompt,expected,truncated",
    [("Short prompt", "Short prompt", False), ("å" * 900, "å" * 512, True)],
    ids=["inline", "truncated"],
)
def test_public_step_exposes_prompt_prefix_and_truncation_fact(
    prompt, expected, truncated
):
    import hashlib

    from eneo.flows.domain.runtime import ResolvedStepMaterial

    text = "Complete document.\n" * 200
    material = ResolvedStepMaterial(
        source_step_id=uuid4(),
        source_attempt_no=2,
        file_id=uuid4(),
        checksum=hashlib.sha256(text.encode()).hexdigest(),
        byte_size=len(text.encode()),
        text=text,
    )
    claimed = _step_result(2, status=FlowStepResultStatus.RUNNING, text="")
    output = StepExecutionOutput(
        input_text=text,
        source_text=text,
        input_source="previous_step",
        used_question_binding=False,
        full_text="answer",
        persisted_text="answer",
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=1,
        num_tokens_output=1,
        effective_prompt=prompt,
        model_parameters_json={},
        materials=(material,),
        max_inline_text_bytes=1025,
    )
    result = build_completed_step_result(
        claimed=claimed,
        run_id=claimed.flow_run_id,
        flow_id=claimed.flow_id,
        tenant_id=claimed.tenant_id,
        step=_runtime_step(2),
        output=output,
        output_payload_json={"text": "answer"},
        execution_hash="hash",
    )
    public = FlowAssembler().to_step_public(result)

    assert result.effective_prompt == expected
    assert result.input_payload_json["effective_prompt_truncated"] is truncated
    assert public.effective_prompt == expected
    assert public.effective_prompt_truncated is truncated
    assert public.input_text_aliases[0].source_step_id == material.source_step_id
    assert public.model_dump()["effective_prompt_truncated"] is truncated
    assert text not in public.model_dump_json()


@pytest.mark.parametrize("prompt_only", [False, True])
def test_public_input_lineage_contains_flat_references_for_each_material(prompt_only):
    import hashlib

    from eneo.flows.domain.runtime import ResolvedStepMaterial
    from eneo.flows.runtime.step_result_builder import build_step_input_payload

    text = "Complete material.\n" * 200
    materials = tuple(
        ResolvedStepMaterial(
            source_step_id=uuid4(),
            source_attempt_no=2,
            file_id=uuid4(),
            checksum=hashlib.sha256(text.encode()).hexdigest(),
            byte_size=len(text.encode()),
            text=text,
        )
        for _ in range(2)
    )
    result = _step_result(3, status=FlowStepResultStatus.COMPLETED, text="answer")
    result.input_payload_json = build_step_input_payload(
        text="" if prompt_only else text + text,
        source_text="",
        input_source="all_previous_steps",
        used_question_binding=False,
        materials=materials,
        max_inline_text_bytes=2048,
    )
    public = FlowAssembler().to_step_public(result)
    assert [alias.file_id for alias in public.input_text_aliases] == [
        m.file_id for m in materials
    ]
    assert [alias.source_step_id for alias in public.input_text_aliases] == [
        m.source_step_id for m in materials
    ]
    assert all(
        set(alias.model_dump())
        == {
            "kind",
            "file_id",
            "checksum",
            "full_text_bytes",
            "inline_text_bytes",
            "preview",
            "source_step_id",
            "source_attempt_no",
        }
        for alias in public.input_text_aliases
    )
    assert text not in public.model_dump_json()


def _runtime_step(step_order: int, *, description: str | None = None) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=description,
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        output_type="text",
        input_type="text",
    )


def _step_result(
    step_order: int, *, status: FlowStepResultStatus, text: str
) -> FlowStepResult:
    now = _now()
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json=None,
        effective_prompt=None,
        output_payload_json={"text": text},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=status,
        error_message=None,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )


def test_build_run_execution_state_keeps_only_completed_results_and_named_steps():
    completed = _step_result(1, status=FlowStepResultStatus.COMPLETED, text="alpha")
    failed = _step_result(2, status=FlowStepResultStatus.FAILED, text="beta")

    state = build_run_execution_state(
        steps=[
            _runtime_step(1, description=" Step One "),
            _runtime_step(2, description=None),
        ],
        persisted_results=[failed, completed],
    )

    assert list(state.completed_by_order) == [1]
    assert [result.step_order for result in state.prior_results] == [1]
    assert state.all_previous_text_before(2) == (
        "<step_1_output>\nalpha\n</step_1_output>\n"
    )
    assert state.step_names_by_order == {1: "Step One"}


def test_build_failed_step_result_carries_optional_payload_and_prompt():
    claimed = _step_result(1, status=FlowStepResultStatus.RUNNING, text="")

    failed = build_failed_step_result(
        claimed=claimed,
        error_code="typed_io_contract_violation",
        error_message="typed failure",
        input_payload_json=build_default_failed_input_payload(
            input_source="flow_input"
        ),
        effective_prompt="Prompt",
    )

    assert failed.status == FlowStepResultStatus.FAILED
    assert failed.error_code == "typed_io_contract_violation"
    assert failed.error_message == "typed failure"
    assert failed.input_payload_json == build_default_failed_input_payload(
        input_source="flow_input"
    )
    assert failed.effective_prompt == "Prompt"


def test_build_completed_step_result_includes_optional_sections_and_hash():
    claimed = _step_result(2, status=FlowStepResultStatus.RUNNING, text="")
    step = _runtime_step(2, description="Second")
    output = StepExecutionOutput(
        input_text="question",
        source_text="source",
        input_source="previous_step",
        used_question_binding=True,
        full_text="answer",
        persisted_text="answer",
        generated_file_ids=[uuid4()],
        tool_calls_metadata=[{"tool": "search"}],
        num_tokens_input=5,
        num_tokens_output=7,
        effective_prompt="Prompt",
        model_parameters_json={"temperature": 0},
        contract_validation={"parse_succeeded": True},
        structured_output={"result": "ok"},
        diagnostics=[StepDiagnostic(code="diag", message="detail", severity="info")],
        artifacts=[{"file_id": "x"}],
        rag_metadata={"status": "success"},
        transcription_metadata={"audio_seconds": 12.5},
    )

    built = build_completed_step_result(
        claimed=claimed,
        run_id=claimed.flow_run_id,
        flow_id=claimed.flow_id,
        tenant_id=claimed.tenant_id,
        step=step,
        output=output,
        output_payload_json={"text": "answer", "structured": {"result": "ok"}},
        execution_hash="abc123",
    )

    assert built.status == FlowStepResultStatus.COMPLETED
    assert built.input_payload_json["transcription"] == {"audio_seconds": 12.5}
    # The step result keeps citation identity; passages live in provenance.
    assert built.input_payload_json["rag"] == {
        "status": "success",
        "citation_sources": [],
        "passage_evidence_location": "attempt_provenance",
    }
    assert built.input_payload_json["contract_validation"] == {"parse_succeeded": True}
    assert built.input_payload_json["diagnostics"] == [
        {"code": "diag", "message": "detail", "severity": "info"}
    ]
    public_step = FlowAssembler().to_step_public(built)
    assert [diagnostic.model_dump() for diagnostic in public_step.diagnostics] == [
        {"code": "diag", "message": "detail", "severity": "info"}
    ]
    assert built.output_payload_json == {
        "text": "answer",
        "structured": {"result": "ok"},
    }
    assert built.flow_step_execution_hash == "abc123"


def test_step_public_exposes_runtime_input_file_ids_from_typed_projection():
    stale_file_id = uuid4()
    relational_file_id = uuid4()
    built = _step_result(
        1,
        status=FlowStepResultStatus.COMPLETED,
        text="answer",
    ).model_copy(
        update={
            "current_attempt_no": 1,
            "input_payload_json": {
                "runtime_input": {
                    "file_ids": [str(stale_file_id)],
                    "extracted_text_length": 120,
                    "input_format": "document",
                }
            },
        }
    )

    public_step = FlowAssembler().to_step_public(
        built,
        runtime_input_file_ids=(relational_file_id,),
    )

    assert public_step.runtime_input_file_ids == [relational_file_id]
    assert public_step.input_payload_json == {
        "runtime_input": {
            "file_ids": [str(stale_file_id)],
            "extracted_text_length": 120,
            "input_format": "document",
        }
    }


def test_step_public_defaults_runtime_input_file_ids_to_empty_list():
    built = _step_result(1, status=FlowStepResultStatus.COMPLETED, text="answer")

    public_step = FlowAssembler().to_step_public(built)

    assert public_step.runtime_input_file_ids == []
    assert public_step.runtime_input_single_recording is False


def test_step_public_says_its_files_are_one_recording():
    built = _step_result(1, status=FlowStepResultStatus.COMPLETED, text="answer")

    public_step = FlowAssembler().to_step_public(
        built,
        runtime_input_file_ids=(uuid4(), uuid4()),
        runtime_input_single_recording=True,
    )

    assert public_step.runtime_input_single_recording is True


def test_build_transcribe_only_rag_metadata_rounds_timeout_to_int():
    metadata = build_transcribe_only_rag_metadata(timeout_seconds=30.9)

    assert metadata["status"] == "skipped_transcribe_only"
    assert metadata["timeout_seconds"] == 30
    assert metadata["references"] == []
