"""Step outputs name their input files next to the ids, and only files whose
row could be read; a run's terminal error carries the taxonomy's guidance."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import FlowRunErrorPublic
from eneo.flows.domain.flow import FlowStepResult
from eneo.flows.enums import FlowStepResultStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_error_taxonomy import FLOW_ERROR_TAXONOMY
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.flow_run_step_input_file import FlowRunStepInputFileRef


def _step_result() -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        status=FlowStepResultStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )


def test_step_outputs_name_the_readable_input_files_in_order():
    named = FlowRunStepInputFileRef(
        file_id=uuid4(), name="underlag.pdf", mimetype="application/pdf"
    )
    unnamed = FlowRunStepInputFileRef(file_id=uuid4(), name=None, mimetype=None)
    untyped = FlowRunStepInputFileRef(file_id=uuid4(), name="notes", mimetype=None)

    public = FlowAssembler().to_step_public(
        _step_result(),
        runtime_input_file_ids=[named.file_id, unnamed.file_id, untyped.file_id],
        runtime_input_files=[named, unnamed, untyped],
    )

    assert public.runtime_input_file_ids == [
        named.file_id,
        unnamed.file_id,
        untyped.file_id,
    ]
    assert [file.model_dump() for file in public.runtime_input_files or []] == [
        {
            "file_id": named.file_id,
            "name": "underlag.pdf",
            "mimetype": "application/pdf",
        },
        {"file_id": untyped.file_id, "name": "notes", "mimetype": None},
    ]


def test_step_outputs_without_read_names_leave_the_list_null():
    public = FlowAssembler().to_step_public(
        _step_result(), runtime_input_file_ids=[uuid4()]
    )

    assert public.runtime_input_files is None


def test_a_run_error_carries_the_taxonomys_guidance_for_its_code():
    error = FlowRunError(
        code=FlowApiErrorCode.STEP_TIMEOUT,
        message="Step 2 exceeded its execution budget.",
        step_order=2,
    )

    public = FlowRunErrorPublic.with_guidance(error)

    entry = FLOW_ERROR_TAXONOMY[FlowApiErrorCode.STEP_TIMEOUT]
    assert (public.user_action, public.consumer_action) == (
        entry.user_action,
        entry.consumer_action,
    )
    assert public.model_dump(exclude={"user_action", "consumer_action"}) == (
        error.model_dump()
    )
