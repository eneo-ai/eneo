from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.database.tables.flow_tables import FlowLiveTranscripts
from eneo.flows.api.flow_models import StepRunInput
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from tests.unittests.flows.test_flow_run_service import (
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


@pytest.fixture
def admission(user):
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
            "input_type": "audio",
            "output_type": "text",
            "output_mode": "transcribe_only",
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "input_format": "audio",
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


async def _submit(case, *, file_ids=None, transcript_id=None, key=None):
    return await case.service.create_run(
        flow_id=case.flow.id,
        input_payload_json=None,
        idempotency_key=key,
        step_inputs={
            case.step.id: SimpleNamespace(
                file_ids=tuple(
                    file_ids if file_ids is not None else [case.files[0].id]
                ),
                live_transcript_id=transcript_id or case.row.id,
            )
        },
    )


def test_run_request_accepts_a_live_transcript_uuid():
    transcript_id, file_id = uuid4(), uuid4()
    value = StepRunInput.model_validate(
        {
            "file_ids": [str(file_id)],
            "live_transcript_id": str(transcript_id),
        }
    )
    assert value.live_transcript_id == transcript_id


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
async def test_foreign_or_expired_live_transcript_refuses_without_binding(
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
    with pytest.raises(NotFoundException) as error:
        await _submit(case)
    assert error.value.code == "flow_run_live_transcript_not_found"
    assert case.row.bound_file_id is None
    case.repo.create.assert_not_awaited()


@pytest.mark.parametrize("count", [0, 2])
async def test_live_transcript_requires_exactly_one_audio_file(admission, count):
    case = admission
    with pytest.raises(BadRequestException) as error:
        await _submit(case, file_ids=[file.id for file in case.files[:count]])
    assert error.value.code == "flow_run_live_transcript_requires_one_audio_file"
    assert case.row.bound_file_id is None
    case.repo.create.assert_not_awaited()


async def test_live_transcript_cannot_be_rebound(admission):
    case = admission
    case.row.bound_file_id = case.files[1].id
    with pytest.raises(ConflictException) as error:
        await _submit(case)
    assert error.value.code == "flow_run_live_transcript_already_bound"
    assert case.row.bound_file_id == case.files[1].id
    case.repo.create.assert_not_awaited()


async def test_live_transcript_binds_and_same_file_retry_is_accepted(admission):
    case = admission
    await _submit(case)
    await _submit(case)
    assert case.row.bound_file_id == case.files[0].id
    assert case.repo.create.await_count == 2
    assert case.repo.create.await_args.kwargs["input_payload_json"]["step_inputs"] == {
        str(case.step.id): {"live_transcript_id": str(case.row.id)},
    }


async def test_an_expired_transcript_already_bound_to_this_file_is_accepted(admission):
    # A retry re-admits the run's own binding; expiry refuses only a first binding.
    case = admission
    case.row.bound_file_id = case.files[0].id
    case.row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await _submit(case)
    assert case.row.bound_file_id == case.files[0].id
    case.repo.create.assert_awaited_once()


async def test_live_transcript_identity_is_part_of_idempotent_replay(admission):
    case = admission
    first = await _submit(case, key="live-recording")
    fingerprint = case.repo.create.await_args.kwargs["request_fingerprint"]
    case.repo.get_idempotent_run.return_value = (first.run, fingerprint)
    repeated = await _submit(case, key="live-recording")
    assert repeated.run.id == first.run.id
    assert repeated.created is False
    with pytest.raises(BadRequestException) as error:
        await _submit(case, key="live-recording", transcript_id=uuid4())
    assert error.value.code == "flow_run_idempotency_conflict"
    case.repo.create.assert_awaited_once()
