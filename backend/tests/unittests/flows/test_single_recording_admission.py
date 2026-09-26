from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flows.api.flow_models import StepRunInput
from eneo.flows.enums import FlowRuntimeInputFormat
from eneo.flows.flow_run_input_envelope import (
    build_initial_run_input_envelope,
    read_single_recording_steps,
)
from eneo.flows.flow_run_step_inputs import (
    FlowRunStepInputFiles,
    validate_single_recording_inputs,
)
from eneo.main.exceptions import BadRequestException
from tests.unittests.flows.test_live_transcript_admission import admission  # noqa: F401


async def _submit(case, *, single_recording, key=None):
    return await case.service.create_run(
        flow_id=case.flow.id,
        input_payload_json=None,
        idempotency_key=key,
        step_inputs={
            case.step.id: FlowRunStepInputFiles(
                file_ids=tuple(file.id for file in case.files),
                single_recording=single_recording,
            )
        },
    )


def test_the_run_request_marks_a_steps_files_as_one_recording():
    assert StepRunInput.model_validate({"single_recording": True}).single_recording
    assert StepRunInput.model_validate({}).single_recording is False


async def test_the_run_records_which_steps_hold_one_recording(admission):  # noqa: F811
    await _submit(admission, single_recording=True)

    payload = admission.repo.create.await_args.kwargs["input_payload_json"]
    assert payload["step_inputs"] == {
        str(admission.step.id): {"single_recording": True}
    }
    assert read_single_recording_steps(payload) == {admission.step.id}


async def test_one_recording_is_part_of_idempotent_replay(admission):  # noqa: F811
    first = await _submit(admission, single_recording=True, key="recording")
    fingerprint = admission.repo.create.await_args.kwargs["request_fingerprint"]
    admission.repo.get_idempotent_run.return_value = (first.run, fingerprint)

    with pytest.raises(BadRequestException) as error:
        await _submit(admission, single_recording=False, key="recording")

    assert error.value.code == "flow_run_idempotency_conflict"


def test_only_an_audio_step_holds_a_recording():
    step_id = uuid4()
    specs = {
        step_id: SimpleNamespace(
            runtime_input=SimpleNamespace(input_format=FlowRuntimeInputFormat.DOCUMENT)
        )
    }

    with pytest.raises(BadRequestException) as error:
        validate_single_recording_inputs(
            step_inputs={step_id: SimpleNamespace(single_recording=True)},
            specs=specs,  # type: ignore[arg-type]
        )

    assert error.value.code == "flow_run_single_recording_requires_audio_step"


def test_the_envelope_keeps_live_transcript_and_recording_facts_together():
    step_id, transcript_id = uuid4(), uuid4()

    payload = build_initial_run_input_envelope(
        normalized_inline_payload=None,
        flow_version=1,
        live_transcript_ids={step_id: transcript_id},
        single_recording_steps=frozenset({step_id}),
    )

    assert payload["step_inputs"] == {
        str(step_id): {
            "live_transcript_id": str(transcript_id),
            "single_recording": True,
        }
    }
