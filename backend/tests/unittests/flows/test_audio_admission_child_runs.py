"""Audio length admission holds only the audio a run will decode.

A run admits its audio once, when it is created: a recording MEASURED longer than
the longest one Eneo allows is refused before the run exists. A child run (a retry
from a completed prefix, a run downstream of a reviewed transcript) reuses its
source run's results and decodes nothing it seeds, so it is not admitted again
for those steps. A length that was never measured (audio uploaded before Eneo
measured length at upload) is not a refusal: the decode enforces the limit.
"""

from __future__ import annotations

import io
import wave
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.files.file_models import FileType
from eneo.flows.domain.flow import FlowStepResult
from eneo.flows.domain.step_output import inline_transcript
from eneo.flows.domain.transcript_regeneration import FlowRunPrefixSeed
from eneo.flows.enums import FlowStepResultStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_input_limits import FlowInputLimits, flow_audio_decode_limits
from eneo.flows.flow_run_input_envelope import (
    read_admitted_audio_seconds,
    with_admitted_audio_seconds,
)
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.flows.runtime.transcription import transcribe_audio_input
from eneo.main.exceptions import TypedIOValidationException
from tests.unit.files import test_audio
from tests.unittests.flows import audio_spool_test_support
from tests.unittests.flows.test_flow_run_service import (
    _flow,
    _flow_repo,
    _flow_run_service,
    _published_definition_json,
    _published_flow_version,
    _run,
    _seed_flow_repo,
    assistant_snapshot,
    flow_run_repo_mock,
)
from tests.unittests.flows.test_flow_transcription import (
    _audio_file,
    _build_executor,
    _patch_run_input_payload,
    _runtime_step,
    _SpaceStub,
    _state,
    _transcribed,
)
from tests.unittests.flows.test_flow_transcription import _run as _executing_run

spool_contract = audio_spool_test_support.spool_contract
ffmpeg = test_audio.ffmpeg

TENANT_LIMIT_SECONDS = 3_600
CHILD_KINDS = ("reused_prefix", "reviewed_transcript_snapshot")


class _AudioCase(SimpleNamespace):
    """A two-step flow whose `audio_step_order` step takes an audio recording."""

    async def create(self, *, prefix_seed: FlowRunPrefixSeed | None = None):
        return await self.service.create_run(
            flow_id=self.flow.id,
            expected_flow_version=1,
            input_payload_json={"x": "y"},
            step_inputs={
                self.audio_step.id: FlowRunStepInputFiles(file_ids=(self.file_id,))
            },
            prefix_seed=prefix_seed,
        )

    def seed(self, kind: str, *, reusing_step_order: int) -> FlowRunPrefixSeed:
        step = next(
            step for step in self.flow.steps if step.step_order == reusing_step_order
        )
        now = datetime.now(timezone.utc)
        source_run = _run(user=self.user, flow_id=self.flow.id)
        result = FlowStepResult(
            id=uuid4(),
            flow_run_id=source_run.id,
            flow_id=self.flow.id,
            tenant_id=self.user.tenant_id,
            step_id=step.id,
            step_order=step.step_order,
            current_attempt_no=1,
            status=FlowStepResultStatus.COMPLETED,
            created_at=now,
            updated_at=now,
        )
        return FlowRunPrefixSeed(
            source_run_id=source_run.id,
            results=(result,),
            provenance={"version": 1, "kind": kind},
            kind=kind,  # type: ignore[arg-type]
            transcript=(
                inline_transcript(
                    text="Reviewed text",
                    source_step_id=step.id,
                    source_attempt_no=1,
                    selector_path=("output", "text"),
                )
                if kind == "reviewed_transcript_snapshot"
                else None
            ),
        )

    @property
    def created_payload(self) -> dict:
        return self.repo.create.await_args.kwargs["input_payload_json"]


def _audio_case(
    user, *, audio_step_order: int, measured_seconds: float | None
) -> _AudioCase:
    """`measured_seconds` None is audio uploaded before Eneo measured its length."""
    flow_repo = _flow_repo()
    repo = flow_run_repo_mock()
    repo.session = MagicMock()
    repo.session.scalar = AsyncMock()
    repo.session.flush = AsyncMock()
    repo.session.in_transaction.return_value = True
    repo.count_active_runs.return_value = 0
    repo.find_by_idempotency_key.return_value = None
    repo.get_idempotent_run.return_value = None
    repo.create.return_value = _run(user=user, flow_id=uuid4())
    version_repo = AsyncMock()
    file_repo = AsyncMock()
    upload_repo = AsyncMock()

    flow = _flow(user=user, published_version=1)
    audio_input = {
        "runtime_input": {
            "enabled": True,
            "required": True,
            "max_files": 1,
            "input_format": "audio",
        }
    }
    steps = [
        step.model_copy(
            update={"input_config": audio_input}
            if step.step_order == audio_step_order
            else {}
        )
        for step in flow.steps
    ]
    flow = flow.model_copy(update={"steps": steps})
    audio_step = steps[audio_step_order - 1]
    _seed_flow_repo(flow_repo, flow)
    version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json=_published_definition_json(
            flow,
            [
                {
                    "step_id": str(step.id),
                    "step_order": step.step_order,
                    "assistant_id": str(step.assistant_id),
                    "assistant_snapshot": assistant_snapshot(step.assistant_id),
                    "input_source": "flow_input"
                    if step.step_order == 1
                    else "previous_step",
                    "input_type": "text",
                    **(
                        {"input_config": step.input_config}
                        if step.step_order == audio_step_order
                        else {}
                    ),
                    "output_mode": "pass_through",
                    "output_type": "json",
                }
                for step in steps
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    file_id = uuid4()
    upload_repo.list_bound_file_ids_for_owner.return_value = {file_id}
    upload_repo.audio_seconds_by_file.return_value = (
        {} if measured_seconds is None else {file_id: measured_seconds}
    )
    file_repo.get_list_by_id_and_owner.return_value = [SimpleNamespace(id=file_id)]
    file_repo.get_infos_with_references_by_ids.return_value = (
        [
            SimpleNamespace(
                id=file_id,
                mimetype="audio/webm",
                size=1024,
                file_type=FileType.AUDIO,
            )
        ],
        [],
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=version_repo,
        runtime_upload_repo=upload_repo,
        file_repo=file_repo,
        max_concurrent_runs=5,
    )
    # The administrator's "longest recording" as it is when the run is created.
    service.settings_service.get_flow_input_limits_resolved = AsyncMock(
        return_value=FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
            audio_max_duration_seconds=TENANT_LIMIT_SECONDS,
        )
    )
    return _AudioCase(
        user=user,
        service=service,
        flow=flow,
        audio_step=audio_step,
        file_id=file_id,
        repo=repo,
        upload_repo=upload_repo,
    )


def _assert_refused_as_too_long(refused: pytest.ExceptionInfo[FlowBadRequestException]):
    assert refused.value.code == FlowApiErrorCode.RUN_AUDIO_EXCEEDS_LIMIT


# --- a child run does not admit the audio whose result it reuses -----------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", CHILD_KINDS)
async def test_a_child_run_reusing_the_audio_step_is_created_for_audio_of_unknown_length(
    user, kind
):
    # Uploaded before Eneo measured length: a retry cannot upload it again.
    case = _audio_case(user, audio_step_order=1, measured_seconds=None)

    created = await case.create(
        prefix_seed=case.seed(kind, reusing_step_order=1),
    )

    assert created.created is True
    case.repo.create.assert_awaited_once()
    case.repo.seed_validated_prefix.assert_awaited_once()
    # Nothing is decoded for a reused step, so nothing is looked up or admitted.
    case.upload_repo.audio_seconds_by_file.assert_not_awaited()
    assert read_admitted_audio_seconds(case.created_payload) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", CHILD_KINDS)
async def test_a_child_run_reusing_the_audio_step_ignores_a_limit_lowered_since_upload(
    user, kind
):
    # Measured at 4 h; the administrator has since lowered the limit to 1 h.
    case = _audio_case(user, audio_step_order=1, measured_seconds=4 * 3_600.0)

    created = await case.create(
        prefix_seed=case.seed(kind, reusing_step_order=1),
    )

    assert created.created is True
    case.upload_repo.audio_seconds_by_file.assert_not_awaited()
    assert read_admitted_audio_seconds(case.created_payload) == {}


@pytest.mark.asyncio
async def test_a_child_run_that_decodes_the_audio_step_again_is_held_to_the_limit(
    user,
):
    # The prefix reuses step 1; the audio step 2 runs again in the child.
    case = _audio_case(user, audio_step_order=2, measured_seconds=4 * 3_600.0)

    with pytest.raises(FlowBadRequestException) as refused:
        await case.create(prefix_seed=case.seed("reused_prefix", reusing_step_order=1))

    _assert_refused_as_too_long(refused)
    assert refused.value.context["step_id"] == str(case.audio_step.id)
    case.repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_child_run_that_decodes_the_audio_step_again_keeps_the_limit_it_was_admitted_under(
    user,
):
    case = _audio_case(user, audio_step_order=2, measured_seconds=60.0)

    await case.create(prefix_seed=case.seed("reused_prefix", reusing_step_order=1))

    assert read_admitted_audio_seconds(case.created_payload) == {
        case.audio_step.id: TENANT_LIMIT_SECONDS
    }


# --- a new run: a known length over the limit is refused; unknown is not ----


@pytest.mark.asyncio
async def test_a_new_run_is_refused_for_audio_measured_over_the_limit(user):
    case = _audio_case(user, audio_step_order=1, measured_seconds=4 * 3_600.0)

    with pytest.raises(FlowBadRequestException) as refused:
        await case.create()

    _assert_refused_as_too_long(refused)
    assert refused.value.context["ceiling"] == TENANT_LIMIT_SECONDS
    case.repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_new_run_is_created_for_audio_of_unknown_length_under_the_limit(user):
    case = _audio_case(user, audio_step_order=1, measured_seconds=None)

    created = await case.create()

    assert created.created is True
    case.upload_repo.audio_seconds_by_file.assert_awaited_once()
    # The decode enforces the limit the run was admitted under.
    assert read_admitted_audio_seconds(case.created_payload) == {
        case.audio_step.id: TENANT_LIMIT_SECONDS
    }


def _wav(seconds: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        handle.writeframes(b"\x00\x00" * 16000 * seconds)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_audio_of_unknown_length_over_the_admitted_limit_is_refused_by_its_decode(
    user, spool_contract, ffmpeg
):
    # The 20 s recording was admitted without a measured length under a 15 s limit;
    # its transcription decodes it under the limit the run recorded.
    case = _audio_case(user, audio_step_order=1, measured_seconds=None)
    case.service.settings_service.get_flow_input_limits_resolved.return_value = (
        FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
            audio_max_duration_seconds=15,
        )
    )
    await case.create()
    admitted = read_admitted_audio_seconds(case.created_payload)
    assert admitted == {case.audio_step.id: 15}
    decode_limits = flow_audio_decode_limits(
        FlowInputLimits(file_max_size_bytes=10_000, audio_max_size_bytes=10_000),
        admitted_seconds=admitted[case.audio_step.id],
    )
    spool_contract.duration_seconds = None  # the real decode, not a stand-in
    recording = SimpleNamespace(
        id=UUID(int=1), name="long.wav", mimetype="audio/wav", blob=_wav(20)
    )

    with pytest.raises(TypedIOValidationException) as refused:
        await transcribe_audio_input(
            files=[recording],
            transcriber=SimpleNamespace(transcribe=AsyncMock()),
            transcription_model=SimpleNamespace(id=uuid4(), name="whisper-1"),
            language="sv",
            step_order=1,
            max_files=5,
            max_inline_text_bytes=100_000,
            open_audio_download=spool_contract.downloads([recording]),
            diarize=False,
            single_recording=True,
            decode_limits=decode_limits,
        )

    assert refused.value.code == FlowApiErrorCode.TYPED_IO_AUDIO_EXCEEDS_LIMIT.value
    assert refused.value.context["limit"] == "duration_seconds"
    spool_contract.assert_finished()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("admitted_seconds", "decoded_under"),
    [(3_600, 3_600), (None, 60)],
    ids=["the limit the run was admitted under", "no admitted limit: tenant's now"],
)
async def test_the_runtime_decodes_a_step_under_the_limit_its_run_was_admitted_under(
    user, spool_contract, admitted_seconds, decoded_under
):
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        user, spool_contract=spool_contract
    )
    # The administrator lowered the longest recording after the run was admitted.
    executor.input_limits = FlowInputLimits(
        file_max_size_bytes=12_000_000,
        audio_max_size_bytes=25_000_000,
        audio_max_duration_seconds=60,
    )
    step = _runtime_step()
    # The persisted fact, written as run creation writes it.
    run = _executing_run(
        user=user,
        payload=with_admitted_audio_seconds(
            None, {step.step_id: admitted_seconds} if admitted_seconds else {}
        ),
    )
    _patch_run_input_payload(flow_run_repo, run)
    file = _audio_file(name="meeting.wav")
    file_service.get_files_by_ids.return_value = [file]
    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )
    transcriber.transcribe = AsyncMock(return_value=_transcribed("ok"))

    await executor._resolve_step_input(
        step=step,
        context=executor.variable_resolver.build_context(run.input_payload_json, []),
        run=run,
        prior_results=[],
        state=_state(),
        version_metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model.id)},
            }
        },
        requested_file_ids=[file.id],
    )

    decoded = transcriber.transcribe.await_args.args[0]
    assert decoded.limits.max_duration_seconds == decoded_under
