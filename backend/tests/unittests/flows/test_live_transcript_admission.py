from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.database.tables.flow_tables import FlowLiveTranscripts
from eneo.flows.api.flow_models import StepRunInput
from eneo.flows.domain.flow import FlowStepResult
from eneo.flows.domain.transcript_regeneration import FlowRunPrefixSeed
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.main.exceptions import BadRequestException
from tests.unittests.flows.test_flow_run_service import (
    _access_policy,
    _flow,
    _flow_repo,
    _flow_run_service,
    _run,
    _runtime_upload_repo,
    _seed_flow_repo,
    _version,
    flow_run_repo_mock,
)
from tests.unittests.flows.test_flow_transcription import _audio_file


def _admission_case(user, *, input_format="audio"):
    model_id = uuid4()
    flow = _flow(
        user=user,
        metadata_json={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model_id)},
            }
        },
    )
    step = flow.steps[0].model_copy(
        update={
            "input_type": input_format,
            "output_type": "text",
            "output_mode": (
                "transcribe_only" if input_format == "audio" else "pass_through"
            ),
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "input_format": input_format,
                    "max_files": 3,
                }
            },
        }
    )
    flow = flow.model_copy(update={"steps": [step]})
    files = [_audio_file(name="one.wav"), _audio_file(name="two.wav")]
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_owner.return_value = files
    file_repo.get_infos_with_references_by_ids.return_value = (files, [])
    run_repo = flow_run_repo_mock()
    run_repo.session = MagicMock()
    run_repo.session.scalar = AsyncMock()
    run_repo.session.flush = AsyncMock()
    run_repo.session.in_transaction.return_value = True
    run_repo.count_active_runs.return_value = 0
    run_repo.get_idempotent_run.return_value = None
    created = _run(user=user, flow_id=flow.id)
    run_repo.create.return_value = created
    flow_repo = _flow_repo()
    _seed_flow_repo(flow_repo, flow)
    version_repo = AsyncMock()
    version_repo.get.return_value = _version(user=user, flow=flow)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=run_repo,
        flow_version_repo=version_repo,
        runtime_upload_repo=_runtime_upload_repo(*(file.id for file in files)),
        file_repo=file_repo,
        access_policy=_access_policy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=run_repo,
        ),
    )
    row = FlowLiveTranscripts(
        id=uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        flow_id=flow.id,
        flow_version=1,
        step_id=step.id,
        model_id=model_id,
        recording_id="recording_123",
        text="Live text.",
        segments=None,
        received_audio_seconds=42,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        bound_file_id=None,
        bound_file_ids=[],
        part_start_samples=[],
    )
    run_repo.session.scalar.return_value = row
    return SimpleNamespace(
        flow=flow,
        step=step,
        files=files,
        row=row,
        service=service,
        repo=run_repo,
        created=created,
    )


@pytest.fixture
def admission(user):
    return _admission_case(user)


async def _submit(
    case,
    *,
    file_ids=None,
    live=True,
    transcript_id=None,
    key=None,
    single_recording=False,
    streamed=True,
    prefix_seed=None,
):
    return await case.service.create_run(
        flow_id=case.flow.id,
        input_payload_json=None,
        idempotency_key=key,
        prefix_seed=prefix_seed,
        step_inputs={
            case.step.id: FlowRunStepInputFiles(
                file_ids=tuple(
                    file_ids if file_ids is not None else [case.files[0].id]
                ),
                live_transcript_id=(transcript_id or case.row.id) if live else None,
                single_recording=single_recording,
                streamed=streamed,
            )
        },
    )


def _recorded(case):
    """What the created run recorded about the step's live text."""
    payload = case.repo.create.await_args.kwargs["input_payload_json"]
    facts = payload["step_inputs"][str(case.step.id)]
    return {
        key: value
        for key, value in facts.items()
        if key != "audio_max_duration_seconds"
    }


def test_run_request_accepts_streamed_audio_with_a_live_transcript():
    transcript_id, file_id = uuid4(), uuid4()
    value = StepRunInput.model_validate(
        {
            "file_ids": [str(file_id)],
            "streamed": True,
            "live_transcript_id": str(transcript_id),
        }
    )
    assert (value.streamed, value.live_transcript_id) == (True, transcript_id)


async def test_a_live_transcript_without_streamed_is_refused(admission):
    case = admission
    with pytest.raises(BadRequestException) as error:
        await _submit(case, streamed=False)
    assert error.value.code == "flow_run_live_transcript_requires_streamed"
    case.repo.create.assert_not_awaited()


async def test_streamed_needs_the_files_of_an_audio_step(admission, user):
    with pytest.raises(BadRequestException) as error:
        await _submit(admission, file_ids=[], live=False)
    assert error.value.code == "flow_run_streamed_requires_audio_files"
    documents = _admission_case(user, input_format="document")
    with pytest.raises(BadRequestException) as error:
        await _submit(documents, live=False)
    assert error.value.code == "flow_run_streamed_requires_audio_files"
    documents.repo.create.assert_not_awaited()


async def test_streamed_audio_without_a_transcript_is_admitted(admission):
    case = admission
    await _submit(case, live=False)
    assert _recorded(case) == {"streamed": True}
    case.repo.session.scalar.assert_not_awaited()


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "user_id",
        "flow_id",
        "flow_version",
        "step_id",
        "model_id",
        "expires_at",
    ],
)
async def test_a_foreign_or_expired_live_transcript_is_recorded_as_not_found(
    admission, field
):
    case = admission
    value = (
        2
        if field == "flow_version"
        else datetime.now(timezone.utc) - timedelta(seconds=1)
        if field == "expires_at"
        else uuid4()
    )
    setattr(case.row, field, value)
    await _submit(case)
    # Nothing of the foreign transcript is recorded beyond the caller's own id.
    assert _recorded(case) == {
        "streamed": True,
        "live_transcript_id": str(case.row.id),
        "live_transcript_refusal": "not_found",
    }
    assert case.row.bound_file_id is None


async def test_several_files_are_one_recording_only_with_single_recording(admission):
    case = admission
    await _submit(case, file_ids=[file.id for file in case.files])
    assert _recorded(case)["live_transcript_refusal"] == "files_mismatch"
    assert case.row.bound_file_id is None


async def test_the_parts_of_a_streamed_recording_bind_in_recording_order(admission):
    case = admission
    case.row.part_start_samples = [16000 * 30]
    parts = [file.id for file in case.files]
    await _submit(case, file_ids=parts, single_recording=True)
    await _submit(case, file_ids=parts, single_recording=True)
    assert (case.row.bound_file_id, case.row.bound_file_ids) == (parts[0], parts)
    assert "live_transcript_refusal" not in _recorded(case)
    # The same files in another order are other audio.
    await _submit(case, file_ids=parts[::-1], single_recording=True)
    assert _recorded(case)["live_transcript_refusal"] == "already_bound"
    assert case.row.bound_file_ids == parts
    assert case.repo.create.await_count == 3


@pytest.mark.parametrize("part_start_samples", [[], [16000, 32000]])
async def test_a_live_transcript_binds_only_every_part_of_its_recording(
    admission, part_start_samples
):
    case = admission
    case.row.part_start_samples = part_start_samples
    await _submit(
        case, file_ids=[file.id for file in case.files], single_recording=True
    )
    assert _recorded(case)["live_transcript_refusal"] == "files_mismatch"
    assert case.row.bound_file_id is None


async def test_a_live_transcript_bound_to_other_files_is_not_rebound(admission):
    case = admission
    case.row.bound_file_id = case.files[1].id
    case.row.bound_file_ids = [case.files[1].id]
    await _submit(case)
    assert _recorded(case)["live_transcript_refusal"] == "already_bound"
    assert case.row.bound_file_ids == [case.files[1].id]


async def test_a_child_run_keeps_a_reused_steps_live_transcript_without_binding_it(
    admission,
):
    """A retry's reused step reports how its audio was submitted. Its transcript
    is imported, so admission binds nothing for it and records no refusal."""
    case = admission
    case.row.bound_file_id = case.files[1].id
    case.row.bound_file_ids = [case.files[1].id]
    reused = cast(FlowStepResult, SimpleNamespace(step_id=case.step.id))

    await _submit(
        case,
        prefix_seed=FlowRunPrefixSeed(
            source_run_id=uuid4(),
            results=(reused,),
            provenance={"version": 1},
            kind="reused_prefix",
        ),
    )

    assert _recorded(case) == {
        "streamed": True,
        "live_transcript_id": str(case.row.id),
    }
    assert case.row.bound_file_ids == [case.files[1].id]
    case.repo.seed_validated_prefix.assert_awaited_once()


async def test_live_transcript_binds_and_same_file_retry_is_accepted(admission):
    case = admission
    await _submit(case)
    await _submit(case)
    assert case.row.bound_file_id == case.files[0].id
    assert case.row.bound_file_ids == [case.files[0].id]
    assert case.repo.create.await_count == 2
    assert _recorded(case) == {
        "streamed": True,
        "live_transcript_id": str(case.row.id),
    }


async def test_an_expired_transcript_already_bound_to_this_file_is_accepted(admission):
    # A retry re-admits the run's own binding; expiry refuses only a first binding.
    case = admission
    case.row.bound_file_id = case.files[0].id
    case.row.bound_file_ids = [case.files[0].id]
    case.row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await _submit(case)
    assert case.row.bound_file_id == case.files[0].id
    assert "live_transcript_refusal" not in _recorded(case)


async def test_the_binding_outcome_is_not_part_of_the_request_fingerprint(admission):
    case = admission
    await _submit(case)
    bound = case.repo.create.await_args.kwargs["request_fingerprint"]
    case.row.bound_file_ids = [case.files[1].id]
    await _submit(case)
    assert _recorded(case)["live_transcript_refusal"] == "already_bound"
    assert case.repo.create.await_args.kwargs["request_fingerprint"] == bound


async def test_a_replay_returns_the_run_before_binding_is_reconsidered(admission):
    case = admission
    first = await _submit(case, key="live-recording")
    fingerprint = case.repo.create.await_args.kwargs["request_fingerprint"]
    case.repo.get_idempotent_run.return_value = (first.run, fingerprint)
    # The response was lost; meanwhile the transcript expired and the model went.
    case.row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    case.row.model_id = uuid4()
    case.repo.session.scalar.reset_mock()
    repeated = await _submit(case, key="live-recording")
    assert (repeated.run.id, repeated.created) == (first.run.id, False)
    case.repo.session.scalar.assert_not_awaited()
    case.repo.create.assert_awaited_once()


@pytest.mark.parametrize(
    "change",
    [{"transcript_id": uuid4()}, {"live": False}],
)
async def test_the_request_fingerprint_covers_the_live_transcript(admission, change):
    case = admission
    first = await _submit(case, key="live-recording")
    fingerprint = case.repo.create.await_args.kwargs["request_fingerprint"]
    case.repo.get_idempotent_run.return_value = (first.run, fingerprint)
    with pytest.raises(BadRequestException) as error:
        await _submit(case, key="live-recording", **change)
    assert error.value.code == "flow_run_idempotency_conflict"
    case.repo.create.assert_awaited_once()


async def test_the_request_fingerprint_covers_streamed(admission):
    case = admission
    await _submit(case, live=False)
    streamed = case.repo.create.await_args.kwargs["request_fingerprint"]
    await _submit(case, live=False, streamed=False)
    assert case.repo.create.await_args.kwargs["request_fingerprint"] != streamed
