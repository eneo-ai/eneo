from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, create_autospec
from uuid import UUID, uuid4

import httpx
import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import File, FileInfo, FileType
from eneo.files.file_service import FileService
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.domain.flow import FlowRun, FlowRunStatus
from eneo.flows.flow_input_limits import FlowInputLimits, resolve_flow_input_limits
from eneo.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    FlowRunInputEnvelopePatch,
)
from eneo.flows.runtime.executor import (
    FlowRunExecutor,
    RunExecutionState,
    RuntimeStep,
)
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.transcription import FlowTranscriptionResult
from eneo.flows.runtime.transcription_runtime import (
    AudioRuntimeDeps,
    AudioRuntimeRequest,
    resolve_transcribe_and_attach_audio_input,
)
from eneo.main.exceptions import NotFoundException, TypedIOValidationException
from tests.unittests.flows import audio_spool_test_support

spool_contract = audio_spool_test_support.spool_contract


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["capacity", "provider"])
async def test_remote_failure_facts_survive_executor_terminalization(
    spool_contract, user, monkeypatch, failure_kind
):
    from eneo.flows.api.flow_models import FlowRunPublic
    from eneo.flows.domain.flow import FlowStepResult
    from eneo.flows.flow_run_error import dump_flow_run_error, parse_flow_run_error
    from eneo.flows.runtime import remote_transcription
    from eneo.flows.runtime.transcription import transcribe_audio_input

    reason = "No GPU capacity. " * 100 if failure_kind == "capacity" else None
    observer = AsyncMock(operation_scope="tenant/run/step/attempt-1")
    observer.started.return_value = uuid4()

    def handle(request):
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-1"})
        if request.url.path.endswith("/result"):
            raise httpx.ReadTimeout("result download timed out", request=request)
        return httpx.Response(
            200,
            json={
                "status": "failed" if failure_kind == "capacity" else "completed",
                "stage": "transcribing",
                "failure_kind": "capacity",
                "error": reason,
            },
        )

    remote = remote_transcription.RemoteFlowTranscriber(
        remote_transcription.RemoteTranscriptionClient(
            base_url="http://transcription.test",
            api_key="test",
            submit_timeout_seconds=10,
            poll_interval_seconds=0.001,
            result_timeout_seconds=10,
            transport=httpx.MockTransport(handle),
        )
    )
    file = _audio_file(name="audio.wav")
    with pytest.raises(TypedIOValidationException) as exc_info:
        await transcribe_audio_input(
            files=[FileInfo.model_validate(file, from_attributes=True)],
            transcriber=remote,
            transcription_model=SimpleNamespace(),
            language="sv",
            step_order=1,
            max_files=1,
            max_inline_text_bytes=1024,
            open_audio_download=spool_contract.downloads([file]),
            transcription_call_observer=observer,
        )
    executor, _, _, _, _ = _build_executor(user, spool_contract=spool_contract)
    executor._terminalize_run = AsyncMock()
    run = _run(user=user)
    step = _runtime_step()
    now = datetime.now(timezone.utc)
    claimed = FlowStepResult(
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=step.step_id,
        step_order=1,
        status="running",
        created_at=now,
        updated_at=now,
    )
    await executor._handle_typed_step_failure(
        run_id=run.id,
        tenant_id=run.tenant_id,
        step=step,
        attempt_no=1,
        claimed=claimed,
        typed_exc=exc_info.value,
        failed_input_payload=None,
    )
    error = executor._terminalize_run.await_args.kwargs["error"]
    public = FlowRunPublic.model_validate(
        run.model_copy(
            update={
                "status": FlowRunStatus.FAILED,
                "error": parse_flow_run_error(dump_flow_run_error(error)),
            }
        ),
        from_attributes=True,
    )
    assert public.error.code.value == "typed_io_transcription_failed"
    assert public.error.retryable is False
    assert public.error.details.phase.value == "transcription"
    assert public.error.details.transcription_failure_kind.value == failure_kind
    assert public.error.details.transcription_service_reason == (
        reason[:512] if reason else None
    )
    if failure_kind == "provider":
        observer.outcome_unknown.assert_awaited_once_with(
            observer.started.return_value, "provider_error"
        )
        assert exc_info.value.__cause__.details["retryable"] is True


def _transcribed(text: str, *, duration_seconds: float = 30.0) -> TranscribedAudio:
    """The transcriber's own result type, so the double cannot drift from it."""

    return TranscribedAudio(text=text, duration_seconds=duration_seconds)


def _audio_file(
    *,
    name: str,
    file_id: UUID | None = None,
    transcription: str | None = None,
    size: int = 1024,
) -> File:
    """Build a runtime audio upload as the real `File` model, fully validated.

    Using the production model rather than a look-alike means a new required
    field on `File` fails here at construction, instead of surfacing later as a
    runtime error in whichever code first trusts it.
    """
    resolved_id = file_id if file_id is not None else uuid4()
    return File(
        id=resolved_id,
        name=name,
        checksum=sha256(resolved_id.bytes).hexdigest(),
        size=size,
        mimetype="audio/wav",
        file_type=FileType.AUDIO,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
        blob=b"audio-bytes",
        transcription=transcription,
    )


class _SpaceStub:
    def __init__(self, models: list[object], default_model: object | None = None):
        self.transcription_models = models
        self._default_model = default_model

    def get_default_transcription_model(self):
        return self._default_model


def _run(*, user, payload: dict | None = None) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.RUNNING,
        cancelled_at=None,
        input_payload_json=payload if payload is not None else {"text": "hello"},
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _runtime_step(
    *, input_type: str = "audio", input_source: str = "flow_input"
) -> RuntimeStep:
    input_config = (
        {
            "runtime_input": {
                "enabled": True,
                "input_format": "audio",
                "required": True,
            }
        }
        if input_type == "audio" and input_source == "flow_input"
        else None
    )
    return RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source=input_source,
        input_bindings=None,
        input_config=input_config,
        output_mode="pass_through",
        output_config=None,
        output_type="text",
        output_contract=None,
        input_type=input_type,
        input_contract=None,
    )


def _patch_run_input_payload(flow_run_repo: AsyncMock, run: FlowRun) -> None:
    async def _update_input_payload(
        *,
        run_id,
        tenant_id,
        input_payload_patch: FlowRunInputEnvelopePatch,
    ):
        assert run_id == run.id
        assert tenant_id == run.tenant_id
        return input_payload_patch.apply_to(run.input_payload_json)

    flow_run_repo.update_input_payload = AsyncMock(side_effect=_update_input_payload)


def _build_executor(
    user,
    *,
    spool_contract,
    max_inline_text_bytes: int = 1024,
    max_audio_files: int = 10,
):
    flow_repo = AsyncMock()
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_run_repo.list_step_input_file_ids = AsyncMock(return_value=[])
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_retained_input_file_ids.return_value = []
    flow_version_repo = AsyncMock()
    flow_run_review_checkpoint_repo = AsyncMock()
    space_repo = AsyncMock()
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    file_repo.get_content_references.return_value = []
    file_content_loader = AsyncMock()
    file_service = create_autospec(FileService, instance=True)
    file_service.repo = file_repo

    def _staged_files() -> list[File]:
        return list(file_service.get_files_by_ids.return_value or [])

    async def _owned_file_infos(file_ids, **_kwargs):
        # The audio path identifies files without their bytes, so the double
        # must hand back identities — never the blob-bearing File. A step that
        # regressed to reading content up front fails here.
        requested = set(file_ids)
        return [
            FileInfo(
                id=staged.id,
                created_at=staged.created_at,
                updated_at=staged.updated_at,
                name=staged.name,
                checksum=staged.checksum,
                size=staged.size,
                mimetype=staged.mimetype,
                file_type=staged.file_type,
                owner_type=staged.owner_type,
                owner_user_id=staged.owner_user_id,
                owner_service_id=staged.owner_service_id,
                tenant_id=staged.tenant_id,
            )
            for staged in _staged_files()
            if staged.id in requested
        ]

    async def _get_file_content(file_id, **_kwargs):
        for staged in _staged_files():
            if staged.id == file_id:
                assert staged.file_type is not FileType.AUDIO, (
                    "Audio must use its download stream"
                )
                return staged
        raise AssertionError(f"unstaged file content requested: {file_id}")

    file_service.get_owned_file_infos.side_effect = _owned_file_infos
    file_service.get_file_content.side_effect = _get_file_content
    file_service.get_audio_download = spool_contract.downloads(_staged_files)
    template_asset_repo = AsyncMock()
    encryption_service = AsyncMock()
    transcriber = AsyncMock()
    executor = FlowRunExecutor(
        runtime_actor=FlowRunActor.from_user(user=user),
        session=session,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=flow_run_review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        file_content_loader=file_content_loader,
        file_service=file_service,
        template_asset_repo=template_asset_repo,
        encryption_service=encryption_service,
        flow_run_terminalizer=AsyncMock(),
        max_inline_text_bytes=max_inline_text_bytes,
        max_audio_files=max_audio_files,
        input_limits=FlowInputLimits(
            file_max_size_bytes=12_000_000,
            audio_max_size_bytes=25_000_000,
        ),
        transcriber=transcriber,
    )
    return executor, flow_run_repo, space_repo, file_service, transcriber


def _state() -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )


@pytest.mark.asyncio
async def test_audio_resolve_transcribes_in_request_order_and_persists_transcript(
    spool_contract, user
):
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user
    )
    file_id_1 = uuid4()
    file_id_2 = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_1 = _audio_file(file_id=file_id_1, name="a.wav")
    file_2 = _audio_file(file_id=file_id_2, name="b.wav")
    file_service.get_files_by_ids.return_value = [file_1, file_2]

    model = SimpleNamespace(
        id=uuid4(),
        name="kb-whisper-large",
        model_name="kb-whisper-large",
        can_access=True,
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )

    async def _tx(
        file_obj,
        transcription_model,
        *,
        file_id,
        language=None,
        diarize=True,
        persist_cache_to_file,
        max_speakers=None,
        observer=None,
    ):
        assert persist_cache_to_file is False
        return _transcribed(f"tx:{file_obj.filename}:{language or 'auto'}")

    transcriber.transcribe = AsyncMock(side_effect=_tx)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        state=_state(),
        version_metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model.id)},
                "transcription_language": "sv",
            }
        },
        requested_file_ids=[file_id_2, file_id_1],
    )

    ordered_names = [
        call.args[0].filename for call in transcriber.transcribe.await_args_list
    ]
    assert ordered_names == ["b.wav", "a.wav"]
    assert [
        call.kwargs["persist_cache_to_file"]
        for call in transcriber.transcribe.await_args_list
    ] == [False, False]
    assert run.input_payload_json[FLOW_INPUT_TRANSCRIPTION_KEY] == resolved.text
    assert context["flow_input"][FLOW_INPUT_TRANSCRIPTION_KEY] == resolved.text
    assert resolved.text.startswith("tx:b.wav:sv")
    assert flow_run_repo.update_input_payload.await_count == 1
    assert resolved.transcription_metadata is not None
    assert resolved.transcription_metadata["files_count"] == 2
    assert resolved.transcription_metadata["language"] == "sv"


@pytest.mark.asyncio
async def test_null_tenant_audio_limit_executes_with_default_capacity(
    spool_contract, user
) -> None:
    limits = resolve_flow_input_limits(
        {"input_limits": {"audio_max_files_per_run": None}},
        defaults=SimpleNamespace(
            session_file_maximum_bytes=12_000_000,
            session_audio_maximum_bytes=25_000_000,
        ),
    )
    executor, _, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract,
        user=user,
        max_audio_files=limits.audio_max_files_per_run,
    )
    files = [_audio_file(name=f"audio-{index}.wav") for index in range(11)]
    file_ids = [file.id for file in files]
    file_service.get_files_by_ids.return_value = files
    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )
    run = _run(user=user, payload={})

    with pytest.raises(TypedIOValidationException, match="11, max 10") as exc_info:
        await executor._resolve_step_input(
            step=_runtime_step(),
            context=executor.variable_resolver.build_context(
                run.input_payload_json, []
            ),
            run=run,
            prior_results=[],
            state=_state(),
            version_metadata={
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_model": {"id": str(model.id)},
                    "transcription_language": "sv",
                }
            },
            requested_file_ids=file_ids,
        )

    assert exc_info.value.code == "typed_io_audio_too_many_files"
    transcriber.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_resolve_passes_no_language_for_auto(spool_contract, user):
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user
    )
    file_id = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_1 = _audio_file(file_id=file_id, name="a.wav")
    file_service.get_files_by_ids.return_value = [file_1]

    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )

    transcriber.transcribe = AsyncMock(return_value=_transcribed("ok"))

    await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        state=_state(),
        version_metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model.id)},
                "transcription_language": "auto",
            }
        },
        requested_file_ids=[file_id],
    )

    assert transcriber.transcribe.await_args.kwargs["language"] is None
    assert transcriber.transcribe.await_args.kwargs["persist_cache_to_file"] is False


@pytest.mark.asyncio
async def test_audio_resolve_ignores_shared_file_transcription_cache(
    spool_contract, user
):
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user
    )
    file_id = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_1 = _audio_file(
        file_id=file_id, name="cached.wav", transcription="stale shared transcript"
    )
    file_service.get_files_by_ids.return_value = [file_1]

    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )

    async def _tx(
        file_obj,
        transcription_model,
        *,
        file_id,
        language=None,
        diarize=True,
        persist_cache_to_file,
        max_speakers=None,
        observer=None,
    ):
        assert file_obj.path.read_bytes() == file_1.blob
        assert file_id == file_1.id
        assert transcription_model is model
        assert language is None
        assert persist_cache_to_file is False
        return _transcribed("fresh flow transcript")

    transcriber.transcribe = AsyncMock(side_effect=_tx)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        state=_state(),
        version_metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model.id)},
                "transcription_language": "auto",
            }
        },
        requested_file_ids=[file_id],
    )

    assert resolved.text == "fresh flow transcript"
    assert file_1.transcription == "stale shared transcript"
    assert run.input_payload_json[FLOW_INPUT_TRANSCRIPTION_KEY] == (
        "fresh flow transcript"
    )


@pytest.mark.asyncio
async def test_audio_resolve_missing_wizard_model_fails_strictly(spool_contract, user):
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user
    )
    file_id = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_1 = _audio_file(file_id=file_id, name="default.wav")
    file_service.get_files_by_ids.return_value = [file_1]

    model = SimpleNamespace(
        id=uuid4(),
        name="kb-whisper-large",
        model_name="kb-whisper-large",
        can_access=True,
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )
    transcriber.transcribe = AsyncMock(return_value=_transcribed("ok"))

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            state=_state(),
            version_metadata={
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_language": "sv",
                }
            },
            requested_file_ids=[file_id],
        )

    assert exc.value.code == "typed_io_transcription_model_missing"
    transcriber.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_resolve_selected_model_unavailable_fails_without_fallback(
    spool_contract, user
):
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user
    )
    file_id = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_1 = _audio_file(file_id=file_id, name="default.wav")
    file_service.get_files_by_ids.return_value = [file_1]

    default_model = SimpleNamespace(
        id=uuid4(),
        name="kb-whisper-large",
        model_name="kb-whisper-large",
        can_access=True,
    )
    selected_but_missing = uuid4()
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[default_model], default_model=default_model)
    )
    transcriber.transcribe = AsyncMock(return_value=_transcribed("ok"))

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            state=_state(),
            version_metadata={
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_model": {"id": str(selected_but_missing)},
                    "transcription_language": "sv",
                }
            },
            requested_file_ids=[file_id],
        )

    assert exc.value.code == "typed_io_transcription_model_unavailable"
    transcriber.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_resolve_near_cap_adds_warning_diagnostic(spool_contract, user):
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user, max_inline_text_bytes=100
    )
    file_id = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_service.get_files_by_ids.return_value = [
        _audio_file(file_id=file_id, name="near.wav")
    ]
    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )
    transcriber.transcribe = AsyncMock(return_value=_transcribed("x" * 90))

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        state=_state(),
        version_metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model.id)},
                "transcription_language": "sv",
            }
        },
        requested_file_ids=[file_id],
    )

    assert any(
        item.code == "typed_io_transcript_near_limit" for item in resolved.diagnostics
    )
    assert resolved.transcription_metadata is not None
    assert resolved.transcription_metadata["transcript_bytes"] >= 90
    assert resolved.transcription_metadata["estimated_tokens"] > 0


@pytest.mark.asyncio
async def test_audio_resolve_multifile_near_cap_keeps_request_order(
    spool_contract, user
):
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user, max_inline_text_bytes=100
    )
    file_id_1 = uuid4()
    file_id_2 = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_1 = _audio_file(file_id=file_id_1, name="a.wav")
    file_2 = _audio_file(file_id=file_id_2, name="b.wav")
    file_service.get_files_by_ids.return_value = [file_1, file_2]
    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )

    async def _tx(
        file_obj,
        transcription_model,
        *,
        file_id,
        language=None,
        diarize=True,
        persist_cache_to_file,
        max_speakers=None,
        observer=None,
    ):
        assert persist_cache_to_file is False
        if file_obj.filename == "b.wav":
            return _transcribed("b" * 40, duration_seconds=12.5)
        return _transcribed("a" * 43, duration_seconds=17.5)

    transcriber.transcribe = AsyncMock(side_effect=_tx)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        state=_state(),
        version_metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model.id)},
                "transcription_language": "sv",
            }
        },
        requested_file_ids=[file_id_2, file_id_1],
    )

    # 40 + 2 separator + 43 = 85 bytes => exactly 85% of 100-byte cap.
    assert resolved.transcription_metadata is not None
    assert resolved.transcription_metadata["transcript_bytes"] == 85
    # The step reports the decoded length of every file it transcribed, together
    # with the model that read them, because it consumes no tokens to report.
    assert resolved.transcription_metadata["audio_seconds"] == 30.0
    assert resolved.transcription_metadata["model"] == "whisper-1"
    assert resolved.transcription_metadata["model_id"] == str(model.id)
    assert resolved.text.startswith("b" * 40)
    assert resolved.text.endswith("a" * 43)
    assert any(
        item.code == "typed_io_transcript_near_limit" for item in resolved.diagnostics
    )
    ordered_names = [
        call.args[0].filename for call in transcriber.transcribe.await_args_list
    ]
    assert ordered_names == ["b.wav", "a.wav"]


@pytest.mark.asyncio
async def test_audio_step_reads_one_payload_at_a_time(spool_contract, user):
    """A step's memory cost must be its largest audio file, not their sum.

    The step resolves against metadata and reads each file's bytes only while
    that file is being transcribed, so ten permitted 200 MiB uploads cannot
    materialize together in one worker.
    """

    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user, max_inline_text_bytes=1000
    )
    file_id_1 = uuid4()
    file_id_2 = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_service.get_files_by_ids.return_value = [
        _audio_file(file_id=file_id_1, name="a.wav"),
        _audio_file(file_id=file_id_2, name="b.wav"),
    ]
    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )

    events: list[str] = []

    async def _tx(file_obj, transcription_model, *, language=None, **_kwargs):
        events.append(f"transcribe {file_obj.filename}")
        return _transcribed(f"text for {file_obj.filename}")

    staged_names = {
        file.id: file.name for file in file_service.get_files_by_ids.return_value
    }
    original_download = file_service.get_audio_download

    async def _recorded_download(file_id):
        events.append(f"load {staged_names[file_id]}")
        return await original_download(file_id)

    file_service.get_audio_download = _recorded_download
    transcriber.transcribe = AsyncMock(side_effect=_tx)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        state=_state(),
        version_metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model.id)},
                "transcription_language": "sv",
            }
        },
        requested_file_ids=[file_id_1, file_id_2],
    )

    # The step never asks for content-bearing files at all...
    file_service.get_files_by_ids.assert_not_awaited()
    assert file_service.get_owned_file_infos.await_count == 2
    # ...and each payload is read immediately before its own transcription, so
    # a prefetching implementation ("load a, load b, transcribe a, ...") fails.
    assert events == [
        "load a.wav",
        "transcribe a.wav",
        "load b.wav",
        "transcribe b.wav",
    ]
    # An audio step contributes no content-bearing files to the model channel.
    assert resolved.files is None
    assert resolved.runtime_input_metadata is not None
    assert [file["name"] for file in resolved.runtime_input_metadata["files"]] == [
        "a.wav",
        "b.wav",
    ]
    # Evidence identity is the contract most exposed by leaving files empty.
    staged = {file.id: file for file in file_service.get_files_by_ids.return_value}
    runtime_edges = [
        edge for edge in resolved.edges if edge.source.kind == "runtime_file"
    ]
    assert [edge.source.file_id for edge in runtime_edges] == [file_id_1, file_id_2]
    assert [edge.source.checksum for edge in runtime_edges] == [
        staged[file_id_1].checksum,
        staged[file_id_2].checksum,
    ]
    assert [edge.source.byte_size for edge in runtime_edges] == [
        staged[file_id_1].size,
        staged[file_id_2].size,
    ]


@pytest.mark.asyncio
async def test_audio_payload_lost_between_identify_and_read_is_a_missing_file(
    spool_contract, user
):
    """Deferred reads must keep the missing-file failure, not blame transcription."""

    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user
    )
    file_id = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_service.get_files_by_ids.return_value = [
        _audio_file(file_id=file_id, name="deleted-midway.wav")
    ]
    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )
    file_service.get_audio_download.error = NotFoundException()

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            state=_state(),
            version_metadata={
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_model": {"id": str(model.id)},
                    "transcription_language": "sv",
                }
            },
            requested_file_ids=[file_id],
        )

    assert exc.value.code == "typed_io_file_not_found"
    transcriber.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_payload_read_failure_stays_inside_the_typed_contract(
    spool_contract, user
):
    """Every way a deferred read can fail must reach the caller as a flow error."""

    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user
    )
    file_id = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_service.get_files_by_ids.return_value = [
        _audio_file(file_id=file_id, name="unreadable.wav")
    ]
    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )
    # Not a missing file: storage unreachable, ownership raced, bytes failed
    # verification. None of these may escape as an untyped exception.
    file_service.get_audio_download.error = RuntimeError("object content down")

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            state=_state(),
            version_metadata={
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_model": {"id": str(model.id)},
                    "transcription_language": "sv",
                }
            },
            requested_file_ids=[file_id],
        )

    assert exc.value.code == "typed_io_transcription_failed"
    transcriber.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_resolve_multifile_overflow_spills_once_in_request_order(
    spool_contract, user
):
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        spool_contract=spool_contract, user=user, max_inline_text_bytes=1024
    )
    file_id_1 = uuid4()
    file_id_2 = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_1 = _audio_file(file_id=file_id_1, name="a.wav")
    file_2 = _audio_file(file_id=file_id_2, name="b.wav")
    file_service.get_files_by_ids.return_value = [file_1, file_2]
    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[model], default_model=model)
    )
    transcriber.transcribe = AsyncMock(
        side_effect=[_transcribed("b" * 550), _transcribed("a" * 550)]
    )

    file_service.save_generated_file.return_value = SimpleNamespace(id=uuid4())
    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        state=_state(),
        version_metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model.id)},
                "transcription_language": "sv",
            }
        },
        requested_file_ids=[file_id_2, file_id_1],
    )

    assert resolved.text == "b" * 550 + "\n\n" + "a" * 550
    file_service.save_generated_file.assert_awaited_once()
    assert run.input_payload_json[FLOW_INPUT_TRANSCRIPTION_KEY]["file_id"] == str(
        file_service.save_generated_file.return_value.id
    )
    ordered_names = [
        call.args[0].filename for call in transcriber.transcribe.await_args_list
    ]
    assert ordered_names == ["b.wav", "a.wav"]


@pytest.mark.asyncio
async def test_audio_resolve_requires_space_transcription_model(spool_contract, user):
    executor, flow_run_repo, space_repo, file_service, _ = _build_executor(
        user, spool_contract=spool_contract
    )
    file_id = uuid4()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    file_service.get_files_by_ids.return_value = [
        _audio_file(file_id=file_id, name="a.wav")
    ]
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[], default_model=None)
    )

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            state=_state(),
            version_metadata={
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_model": {"id": str(uuid4())},
                    "transcription_language": "sv",
                }
            },
            requested_file_ids=[file_id],
        )

    assert exc.value.code == "typed_io_transcription_model_unavailable"


@pytest.mark.asyncio
async def test_resolve_transcribe_attach_updates_payload_context_and_audits(
    spool_contract, user, monkeypatch
):
    flow_run_repo = AsyncMock()
    audit_service = AsyncMock()
    transcriber = AsyncMock()
    space_repo = AsyncMock()
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = {"flow_input": {}}

    from eneo.flows.runtime.transcription import TranscriptSourcePreparation

    transcription_result = FlowTranscriptionResult(
        source_preparation=TranscriptSourcePreparation(
            files_count=1,
            segments=[],
            speaker_review=None,
            words=[],
            words_omitted_reason=None,
        ),
        text="transcribed text",
        file_ids=[uuid4()],
        model_id=uuid4(),
        model_name="kb-whisper-large",
        language="sv",
        transcript_bytes=16,
        estimated_tokens=4,
        audio_seconds=95.5,
        elapsed_ms=1234,
        files_count=1,
        near_inline_limit=True,
    )
    resolver = AsyncMock(return_value=transcription_result)
    monkeypatch.setattr(
        "eneo.flows.runtime.transcription_runtime.resolve_and_transcribe_audio_for_step",
        resolver,
    )

    request = AudioRuntimeRequest(
        run=run,
        step=step,
        context=context,
        version_metadata={"wizard": {}},
        files=[],
        requested_ids=[],
        max_audio_files=10,
        max_inline_text_bytes=1024,
    )
    deps = AudioRuntimeDeps(
        stage_transcript_source=lambda reference, source: None,
        commit=AsyncMock(),
        apply_output_cap=AsyncMock(side_effect=lambda **kw: (kw["text"], [])),
        transcriber=transcriber,
        space_repo=space_repo,
        flow_run_repo=flow_run_repo,
        audit_service=audit_service,
        actor=FlowRunActor.from_user(user=user),
        open_audio_download=spool_contract.downloads([]),
    )

    result = await resolve_transcribe_and_attach_audio_input(
        request=request,
        deps=deps,
    )

    assert result.text == "transcribed text"
    assert result.transcription_metadata["language"] == "sv"
    assert result.near_inline_limit_message is not None
    assert run.input_payload_json[FLOW_INPUT_TRANSCRIPTION_KEY] == "transcribed text"
    assert context[FLOW_INPUT_TRANSCRIPTION_KEY] == "transcribed text"
    assert context["flow_input"][FLOW_INPUT_TRANSCRIPTION_KEY] == "transcribed text"
    flow_run_repo.update_input_payload.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()
    call = audit_service.log_async.await_args.kwargs
    assert call["action"] == ActionType.FLOW_RUN_AUDIO_TRANSCRIBED
    assert call["entity_type"] == EntityType.FLOW_RUN
    assert call["entity_id"] == run.id
    assert call["outcome"] == Outcome.SUCCESS
    metadata = call["metadata"]
    assert metadata["extra"]["step_order"] == step.step_order
    assert metadata["extra"]["language"] == "sv"
    assert metadata["extra"]["files_count"] == 1


@pytest.mark.asyncio
async def test_resolve_transcribe_attach_swallow_audit_errors(
    spool_contract, user, monkeypatch
):
    flow_run_repo = AsyncMock()
    audit_service = AsyncMock()
    audit_service.log_async = AsyncMock(side_effect=RuntimeError("audit down"))
    step = _runtime_step()
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)
    context = {"flow_input": {}}

    from eneo.flows.runtime.transcription import TranscriptSourcePreparation

    transcription_result = FlowTranscriptionResult(
        source_preparation=TranscriptSourcePreparation(
            files_count=1,
            segments=[],
            speaker_review=None,
            words=[],
            words_omitted_reason=None,
        ),
        text="transcribed text",
        file_ids=[uuid4()],
        model_id=uuid4(),
        model_name="kb-whisper-large",
        language="sv",
        transcript_bytes=16,
        estimated_tokens=4,
        audio_seconds=95.5,
        elapsed_ms=1234,
        files_count=1,
        near_inline_limit=False,
    )
    monkeypatch.setattr(
        "eneo.flows.runtime.transcription_runtime.resolve_and_transcribe_audio_for_step",
        AsyncMock(return_value=transcription_result),
    )

    request = AudioRuntimeRequest(
        run=run,
        step=step,
        context=context,
        version_metadata={"wizard": {}},
        files=[],
        requested_ids=[],
        max_audio_files=10,
        max_inline_text_bytes=1024,
    )
    deps = AudioRuntimeDeps(
        stage_transcript_source=lambda reference, source: None,
        commit=AsyncMock(),
        apply_output_cap=AsyncMock(side_effect=lambda **kw: (kw["text"], [])),
        transcriber=AsyncMock(),
        space_repo=AsyncMock(),
        flow_run_repo=flow_run_repo,
        audit_service=audit_service,
        actor=FlowRunActor.from_user(user=user),
        open_audio_download=spool_contract.downloads([]),
    )

    result = await resolve_transcribe_and_attach_audio_input(
        request=request,
        deps=deps,
    )

    assert result.text == "transcribed text"
    flow_run_repo.update_input_payload.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()
