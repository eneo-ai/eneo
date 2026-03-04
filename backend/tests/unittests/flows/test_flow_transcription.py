from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome
from intric.flows.flow import FlowRun, FlowRunStatus
from intric.flows.runtime.executor import FlowRunExecutor, RunExecutionState, RuntimeStep
from intric.flows.runtime.transcription import FlowTranscriptionResult
from intric.flows.runtime.transcription_runtime import (
    AudioRuntimeDeps,
    AudioRuntimeRequest,
    FLOW_INPUT_TRANSCRIPTION_KEY,
    resolve_transcribe_and_attach_audio_input,
)
from intric.main.exceptions import TypedIOValidationException


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
        user_id=user.id,
        tenant_id=user.tenant_id,
        status=FlowRunStatus.RUNNING,
        cancelled_at=None,
        input_payload_json=payload or {"text": "hello"},
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _runtime_step(*, input_type: str = "audio", input_source: str = "flow_input") -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source=input_source,
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        output_type="text",
        output_contract=None,
        input_type=input_type,
        input_contract=None,
    )


def _build_executor(user, *, max_inline_text_bytes: int = 1024):
    flow_repo = AsyncMock()
    flow_repo.session = AsyncMock()
    flow_repo.session.commit = AsyncMock()
    flow_repo.session.rollback = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_repo = AsyncMock()
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    encryption_service = AsyncMock()
    transcriber = AsyncMock()
    executor = FlowRunExecutor(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        encryption_service=encryption_service,
        max_inline_text_bytes=max_inline_text_bytes,
        transcriber=transcriber,
    )
    return executor, flow_run_repo, space_repo, file_repo, transcriber


def _state() -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )


@pytest.mark.asyncio
async def test_audio_resolve_transcribes_in_request_order_and_persists_transcript(user):
    executor, flow_run_repo, space_repo, file_repo, transcriber = _build_executor(user)
    file_id_1 = uuid4()
    file_id_2 = uuid4()
    run = _run(user=user, payload={"file_ids": [str(file_id_2), str(file_id_1)]})
    context = executor.variable_resolver.build_context(run.input_payload_json, [])
    step = _runtime_step()

    file_1 = SimpleNamespace(id=file_id_1, name="a.wav", mimetype="audio/wav", transcription=None)
    file_2 = SimpleNamespace(id=file_id_2, name="b.wav", mimetype="audio/wav", transcription=None)
    file_repo.get_list_by_id_and_user = AsyncMock(return_value=[file_1, file_2])

    model = SimpleNamespace(id=uuid4(), name="kb-whisper-large", model_name="kb-whisper-large", can_access=True)
    space_repo.get_space_by_assistant = AsyncMock(return_value=_SpaceStub(models=[model], default_model=model))

    async def _tx(file_obj, transcription_model, *, language=None):
        return f"tx:{file_obj.name}:{language or 'auto'}"

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
    )

    ordered_names = [call.args[0].name for call in transcriber.transcribe.await_args_list]
    assert ordered_names == ["b.wav", "a.wav"]
    assert run.input_payload_json["transkribering"] == resolved.text
    assert context["flow_input"]["transkribering"] == resolved.text
    assert resolved.text.startswith("tx:b.wav:sv")
    assert flow_run_repo.update_input_payload.await_count == 1
    assert resolved.transcription_metadata is not None
    assert resolved.transcription_metadata["files_count"] == 2
    assert resolved.transcription_metadata["language"] == "sv"


@pytest.mark.asyncio
async def test_audio_resolve_passes_no_language_for_auto(user):
    executor, _, space_repo, file_repo, transcriber = _build_executor(user)
    file_id = uuid4()
    run = _run(user=user, payload={"file_ids": [str(file_id)]})
    context = executor.variable_resolver.build_context(run.input_payload_json, [])
    step = _runtime_step()

    file_1 = SimpleNamespace(id=file_id, name="a.wav", mimetype="audio/wav", transcription=None)
    file_repo.get_list_by_id_and_user = AsyncMock(return_value=[file_1])

    model = SimpleNamespace(id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True)
    space_repo.get_space_by_assistant = AsyncMock(return_value=_SpaceStub(models=[model], default_model=model))

    transcriber.transcribe = AsyncMock(return_value="ok")

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
    )

    assert transcriber.transcribe.await_args.kwargs["language"] is None


@pytest.mark.asyncio
async def test_audio_resolve_missing_wizard_model_fails_strictly(user):
    executor, _, space_repo, file_repo, transcriber = _build_executor(user)
    file_id = uuid4()
    run = _run(user=user, payload={"file_ids": [str(file_id)]})
    context = executor.variable_resolver.build_context(run.input_payload_json, [])
    step = _runtime_step()

    file_1 = SimpleNamespace(id=file_id, name="default.wav", mimetype="audio/wav", transcription=None)
    file_repo.get_list_by_id_and_user = AsyncMock(return_value=[file_1])

    model = SimpleNamespace(id=uuid4(), name="kb-whisper-large", model_name="kb-whisper-large", can_access=True)
    space_repo.get_space_by_assistant = AsyncMock(return_value=_SpaceStub(models=[model], default_model=model))
    transcriber.transcribe = AsyncMock(return_value="ok")

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
        )

    assert exc.value.code == "typed_io_transcription_model_missing"
    transcriber.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_resolve_selected_model_unavailable_fails_without_fallback(user):
    executor, _, space_repo, file_repo, transcriber = _build_executor(user)
    file_id = uuid4()
    run = _run(user=user, payload={"file_ids": [str(file_id)]})
    context = executor.variable_resolver.build_context(run.input_payload_json, [])
    step = _runtime_step()

    file_1 = SimpleNamespace(id=file_id, name="default.wav", mimetype="audio/wav", transcription=None)
    file_repo.get_list_by_id_and_user = AsyncMock(return_value=[file_1])

    default_model = SimpleNamespace(id=uuid4(), name="kb-whisper-large", model_name="kb-whisper-large", can_access=True)
    selected_but_missing = uuid4()
    space_repo.get_space_by_assistant = AsyncMock(
        return_value=_SpaceStub(models=[default_model], default_model=default_model)
    )
    transcriber.transcribe = AsyncMock(return_value="ok")

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
        )

    assert exc.value.code == "typed_io_transcription_model_unavailable"
    transcriber.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_resolve_overflow_raises_specific_typed_error(user):
    executor, _, space_repo, file_repo, transcriber = _build_executor(user, max_inline_text_bytes=20)
    file_id = uuid4()
    run = _run(user=user, payload={"file_ids": [str(file_id)]})
    context = executor.variable_resolver.build_context(run.input_payload_json, [])
    step = _runtime_step()

    file_repo.get_list_by_id_and_user = AsyncMock(
        return_value=[SimpleNamespace(id=file_id, name="big.wav", mimetype="audio/wav", transcription=None)]
    )
    model = SimpleNamespace(id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True)
    space_repo.get_space_by_assistant = AsyncMock(return_value=_SpaceStub(models=[model], default_model=model))
    transcriber.transcribe = AsyncMock(return_value="x" * 200)

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
        )

    assert exc.value.code == "typed_io_transcript_too_large"


@pytest.mark.asyncio
async def test_audio_resolve_near_cap_adds_warning_diagnostic(user):
    executor, _, space_repo, file_repo, transcriber = _build_executor(user, max_inline_text_bytes=100)
    file_id = uuid4()
    run = _run(user=user, payload={"file_ids": [str(file_id)]})
    context = executor.variable_resolver.build_context(run.input_payload_json, [])
    step = _runtime_step()

    file_repo.get_list_by_id_and_user = AsyncMock(
        return_value=[SimpleNamespace(id=file_id, name="near.wav", mimetype="audio/wav", transcription=None)]
    )
    model = SimpleNamespace(id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True)
    space_repo.get_space_by_assistant = AsyncMock(return_value=_SpaceStub(models=[model], default_model=model))
    transcriber.transcribe = AsyncMock(return_value="x" * 90)

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
    )

    assert any(item.code == "typed_io_transcript_near_limit" for item in resolved.diagnostics)
    assert resolved.transcription_metadata is not None
    assert resolved.transcription_metadata["transcript_bytes"] >= 90
    assert resolved.transcription_metadata["estimated_tokens"] > 0


@pytest.mark.asyncio
async def test_audio_resolve_multifile_near_cap_keeps_request_order(user):
    executor, _, space_repo, file_repo, transcriber = _build_executor(user, max_inline_text_bytes=100)
    file_id_1 = uuid4()
    file_id_2 = uuid4()
    run = _run(user=user, payload={"file_ids": [str(file_id_2), str(file_id_1)]})
    context = executor.variable_resolver.build_context(run.input_payload_json, [])
    step = _runtime_step()

    file_1 = SimpleNamespace(id=file_id_1, name="a.wav", mimetype="audio/wav", transcription=None)
    file_2 = SimpleNamespace(id=file_id_2, name="b.wav", mimetype="audio/wav", transcription=None)
    file_repo.get_list_by_id_and_user = AsyncMock(return_value=[file_1, file_2])
    model = SimpleNamespace(id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True)
    space_repo.get_space_by_assistant = AsyncMock(return_value=_SpaceStub(models=[model], default_model=model))

    async def _tx(file_obj, transcription_model, *, language=None):
        if file_obj.name == "b.wav":
            return "b" * 40
        return "a" * 43

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
    )

    # 40 + 2 separator + 43 = 85 bytes => exactly 85% of 100-byte cap.
    assert resolved.transcription_metadata is not None
    assert resolved.transcription_metadata["transcript_bytes"] == 85
    assert resolved.text.startswith("b" * 40)
    assert resolved.text.endswith("a" * 43)
    assert any(item.code == "typed_io_transcript_near_limit" for item in resolved.diagnostics)
    ordered_names = [call.args[0].name for call in transcriber.transcribe.await_args_list]
    assert ordered_names == ["b.wav", "a.wav"]


@pytest.mark.asyncio
async def test_audio_resolve_multifile_overflow_raises_typed_error(user):
    executor, _, space_repo, file_repo, transcriber = _build_executor(user, max_inline_text_bytes=90)
    file_id_1 = uuid4()
    file_id_2 = uuid4()
    run = _run(user=user, payload={"file_ids": [str(file_id_2), str(file_id_1)]})
    context = executor.variable_resolver.build_context(run.input_payload_json, [])
    step = _runtime_step()

    file_1 = SimpleNamespace(id=file_id_1, name="a.wav", mimetype="audio/wav", transcription=None)
    file_2 = SimpleNamespace(id=file_id_2, name="b.wav", mimetype="audio/wav", transcription=None)
    file_repo.get_list_by_id_and_user = AsyncMock(return_value=[file_1, file_2])
    model = SimpleNamespace(id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True)
    space_repo.get_space_by_assistant = AsyncMock(return_value=_SpaceStub(models=[model], default_model=model))
    transcriber.transcribe = AsyncMock(side_effect=["b" * 45, "a" * 45])

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
        )

    assert exc.value.code == "typed_io_transcript_too_large"
    ordered_names = [call.args[0].name for call in transcriber.transcribe.await_args_list]
    assert ordered_names == ["b.wav", "a.wav"]


@pytest.mark.asyncio
async def test_audio_resolve_requires_space_transcription_model(user):
    executor, _, space_repo, file_repo, _ = _build_executor(user)
    file_id = uuid4()
    run = _run(user=user, payload={"file_ids": [str(file_id)]})
    context = executor.variable_resolver.build_context(run.input_payload_json, [])
    step = _runtime_step()

    file_repo.get_list_by_id_and_user = AsyncMock(
        return_value=[SimpleNamespace(id=file_id, name="a.wav", mimetype="audio/wav", transcription=None)]
    )
    space_repo.get_space_by_assistant = AsyncMock(return_value=_SpaceStub(models=[], default_model=None))

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
        )

    assert exc.value.code == "typed_io_transcription_model_unavailable"


@pytest.mark.asyncio
async def test_resolve_transcribe_attach_updates_payload_context_and_audits(user, monkeypatch):
    flow_run_repo = AsyncMock()
    audit_service = AsyncMock()
    transcriber = AsyncMock()
    space_repo = AsyncMock()
    run = _run(user=user, payload={"file_ids": []})
    context = {"flow_input": {"file_ids": []}}
    step = _runtime_step()

    transcription_result = FlowTranscriptionResult(
        text="transcribed text",
        file_ids=[uuid4()],
        model_name="kb-whisper-large",
        language="sv",
        transcript_bytes=16,
        estimated_tokens=4,
        elapsed_ms=1234,
        files_count=1,
        used_cache=False,
        cached_files_count=0,
        near_inline_limit=True,
    )
    resolver = AsyncMock(return_value=transcription_result)
    monkeypatch.setattr(
        "intric.flows.runtime.transcription_runtime.resolve_and_transcribe_audio_for_step",
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
        transcriber=transcriber,
        space_repo=space_repo,
        flow_run_repo=flow_run_repo,
        audit_service=audit_service,
        actor=user,
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
async def test_resolve_transcribe_attach_swallow_audit_errors(user, monkeypatch):
    flow_run_repo = AsyncMock()
    audit_service = AsyncMock()
    audit_service.log_async = AsyncMock(side_effect=RuntimeError("audit down"))
    run = _run(user=user, payload={"file_ids": []})
    context = {"flow_input": {"file_ids": []}}
    step = _runtime_step()

    transcription_result = FlowTranscriptionResult(
        text="transcribed text",
        file_ids=[uuid4()],
        model_name="kb-whisper-large",
        language="sv",
        transcript_bytes=16,
        estimated_tokens=4,
        elapsed_ms=1234,
        files_count=1,
        used_cache=False,
        cached_files_count=0,
        near_inline_limit=False,
    )
    monkeypatch.setattr(
        "intric.flows.runtime.transcription_runtime.resolve_and_transcribe_audio_for_step",
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
        transcriber=AsyncMock(),
        space_repo=AsyncMock(),
        flow_run_repo=flow_run_repo,
        audit_service=audit_service,
        actor=user,
    )

    result = await resolve_transcribe_and_attach_audio_input(
        request=request,
        deps=deps,
    )

    assert result.text == "transcribed text"
    flow_run_repo.update_input_payload.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()
