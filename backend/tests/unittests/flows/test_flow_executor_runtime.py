from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.outcome import Outcome
from intric.flows.assistant_execution_snapshot import (
    build_assistant_execution_snapshot,
    stable_hash,
)
from intric.flows.enums import FlowRunTerminalSource
from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from intric.flows.flow import (
    FlowVersion as FlowVersionModel,
)
from intric.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from intric.flows.runtime.document_rendering.limits import DocumentRenderLimits
from intric.flows.runtime.executor import (
    FlowRunExecutor,
    FlowRunExecutorConfig,
    RunExecutionState,
    RuntimeStep,
    StepExecutionOutput,
    StepInputValue,
)
from intric.main.exceptions import BadRequestException, TypedIOValidationException

_DEFAULT_SNAPSHOT_MODEL_ID = UUID("00000000-0000-0000-0000-000000000001")
_DEFAULT_SNAPSHOT_PROMPT = "Execute this flow step."


def _run(*, status: FlowRunStatus, user) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=status,
        cancelled_at=None,
        input_payload_json={"text": "hello"},
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _default_snapshot_assistant(assistant_id: UUID | str) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(str(assistant_id)),
        origin="flow_managed",
        prompt=SimpleNamespace(text=_DEFAULT_SNAPSHOT_PROMPT),
        completion_model=SimpleNamespace(
            id=_DEFAULT_SNAPSHOT_MODEL_ID,
            name="gpt-5.4-nano",
            nickname="Nano",
            litellm_model_name="openai/gpt-5.4-nano",
        ),
        completion_model_kwargs={"temperature": 0.2},
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        mcp_servers=[],
    )


def _definition_step_with_default_snapshot(step: object) -> object:
    if not isinstance(step, dict):
        return step
    normalized = dict(step)
    if "assistant_snapshot" in normalized:
        return normalized
    assistant_id = normalized.get("assistant_id")
    if assistant_id is None:
        return normalized
    snapshot = build_assistant_execution_snapshot(
        assistant=_default_snapshot_assistant(str(assistant_id)),
        mcp_server_entities=[],
    )
    if snapshot is not None:
        normalized["assistant_snapshot"] = snapshot
    return normalized


def FlowVersion(
    *,
    flow_id,
    version,
    tenant_id,
    definition_checksum,
    definition_json,
    created_at,
    updated_at,
) -> FlowVersionModel:
    """Build canonical versions unless a test intentionally passes a bad checksum."""
    if definition_checksum == "checksum":
        if isinstance(definition_json.get("steps"), list):
            schema_version_provided = "schema_version" in definition_json
            steps = definition_json["steps"]
            if not schema_version_provided:
                steps = [_definition_step_with_default_snapshot(step) for step in steps]
            definition_json = {
                "schema_version": definition_json.get(
                    "schema_version", FLOW_DEFINITION_SCHEMA_VERSION
                ),
                "flow_id": definition_json.get("flow_id", str(flow_id)),
                "name": definition_json.get("name", "Test flow"),
                "description": definition_json.get("description"),
                "metadata_json": definition_json.get("metadata_json"),
                "steps": steps,
            }
        definition_checksum = stable_hash(definition_json)
    return FlowVersionModel(
        flow_id=flow_id,
        version=version,
        tenant_id=tenant_id,
        definition_checksum=definition_checksum,
        definition_json=definition_json,
        created_at=created_at,
        updated_at=updated_at,
    )


def _claimed_step_result(
    *, run_id, flow_id, tenant_id, step_id, assistant_id
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=step_id,
        step_order=1,
        assistant_id=assistant_id,
        input_payload_json=None,
        effective_prompt=None,
        output_payload_json=None,
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.RUNNING,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )


def _run_get_mock(*runs: FlowRun) -> AsyncMock:
    sequence = list(runs)

    async def _get(*args, **kwargs):
        if sequence:
            if len(sequence) == 1:
                return sequence[0]
            return sequence.pop(0)
        raise AssertionError("Flow run get mock exhausted without fallback run")

    return AsyncMock(side_effect=_get)


def _build_executor(user):
    flow_repo = AsyncMock()
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_repo = AsyncMock()

    async def _get_space_by_assistant(*, assistant_id):
        assistant = _default_snapshot_assistant(assistant_id)
        return SimpleNamespace(get_assistant=lambda assistant_id: assistant)

    space_repo.get_space_by_assistant = AsyncMock(side_effect=_get_space_by_assistant)
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    template_asset_service = AsyncMock()
    encryption_service = AsyncMock()
    flow_run_terminalizer = SimpleNamespace()

    async def _terminalize_run(**kwargs):
        return SimpleNamespace(
            run=SimpleNamespace(status=kwargs["target_status"]),
            did_transition=True,
            target_status=kwargs["target_status"],
            source=kwargs["source"],
            audit_outbox_id=uuid4(),
        )

    flow_run_terminalizer.terminalize_run = AsyncMock(side_effect=_terminalize_run)
    executor = FlowRunExecutor(
        user=user,
        session=session,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        template_asset_service=template_asset_service,
        encryption_service=encryption_service,
        flow_run_terminalizer=flow_run_terminalizer,
        max_inline_text_bytes=1024 * 1024,
    )
    return executor, flow_repo, flow_run_repo, flow_version_repo


def _empty_execution_state() -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )


@pytest.mark.asyncio
async def test_flow_is_active_delegates_to_flow_repo(user):
    executor, flow_repo, _, _ = _build_executor(user)
    flow_id = uuid4()
    tenant_id = uuid4()
    flow_repo.is_active = AsyncMock(return_value=True)

    active = await executor._flow_is_active(flow_id=flow_id, tenant_id=tenant_id)

    assert active is True
    flow_repo.is_active.assert_awaited_once_with(flow_id=flow_id, tenant_id=tenant_id)


def test_executor_accepts_grouped_config(user):
    flow_repo = AsyncMock()
    session = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_repo = AsyncMock()
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    template_asset_service = AsyncMock()
    encryption_service = AsyncMock()
    config = FlowRunExecutorConfig(
        max_inline_text_bytes=2048,
        max_audio_files=7,
        max_generic_files=3,
        http_request_timeout_seconds=11.0,
        http_max_timeout_seconds=22.0,
        http_allow_private_networks=True,
        rag_retrieval_timeout_seconds=44.0,
        rag_max_reference_sources=12,
        rag_max_chunks_per_source=6,
        document_render_limits=DocumentRenderLimits(max_source_chars=123),
    )

    executor = FlowRunExecutor(
        user=user,
        session=session,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        template_asset_service=template_asset_service,
        encryption_service=encryption_service,
        config=config,
    )

    assert executor.max_inline_text_bytes == 2048
    assert executor.max_audio_files == 7
    assert executor.max_generic_files == 3
    assert executor.http_request_timeout_seconds == 11.0
    assert executor.http_max_timeout_seconds == 22.0
    assert executor.http_allow_private_networks is True
    assert executor.rag_retrieval_timeout_seconds == 44.0
    assert executor.rag_max_reference_sources == 12
    assert executor.rag_max_chunks_per_source == 6
    assert executor.document_render_service.limits.max_source_chars == 123


def _assistant_for_execute_step(*, has_knowledge: bool):
    model_kwargs = MagicMock()
    model_kwargs.model_dump.return_value = {}
    assistant = MagicMock()
    assistant.has_knowledge.return_value = has_knowledge
    assistant.collections = [MagicMock()] if has_knowledge else []
    assistant.websites = []
    assistant.integration_knowledge_list = []
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = model_kwargs
    assistant.completion_model = SimpleNamespace(
        id=uuid4(), name="gpt-4o-mini", provider_type="openai"
    )
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            completion="answer",
            total_token_count=42,
        )
    )
    return assistant


@pytest.mark.asyncio
async def test_webhook_failure_keeps_completed_step_evidence(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    async def _get_run(*args, **kwargs):
        if flow_run_repo.get.await_count == 1:
            return queued_run
        return running_run

    flow_run_repo.get = AsyncMock(side_effect=_get_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "http_post",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="result",
            persisted_text="result",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=11,
            effective_prompt="prompt",
            model_parameters_json={"temperature": 0.2},
            contract_validation={
                "schema_type_hint": "object",
                "parse_attempted": True,
                "parse_succeeded": True,
                "candidate_type": "dict",
            },
            transcription_metadata={
                "model": "kb-whisper-large",
                "language": "sv",
                "files_count": 1,
                "elapsed_ms": 1200,
            },
        )
    )
    executor._deliver_webhook = AsyncMock(
        side_effect=RuntimeError("webhook unavailable")
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result["status"] == "failed"
    assert flow_repo.save_step_result.await_count == 2
    first_saved = flow_repo.save_step_result.await_args_list[0].args[1]
    second_saved = flow_repo.save_step_result.await_args_list[1].args[1]
    assert first_saved.status == FlowStepResultStatus.COMPLETED
    assert first_saved.input_payload_json == {
        "text": "hello",
        "source_text": "hello",
        "input_source": "flow_input",
        "used_question_binding": False,
        "legacy_prompt_binding_used": False,
        "transcription": {
            "model": "kb-whisper-large",
            "language": "sv",
            "files_count": 1,
            "elapsed_ms": 1200,
        },
        "contract_validation": {
            "schema_type_hint": "object",
            "parse_attempted": True,
            "parse_succeeded": True,
            "candidate_type": "dict",
        },
    }
    assert second_saved.status == FlowStepResultStatus.COMPLETED
    assert second_saved.output_payload_json["webhook_delivered"] is False
    assert "webhook_error" in second_saved.output_payload_json


@pytest.mark.asyncio
async def test_webhook_failure_logs_exception_context(user, monkeypatch):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    async def _get_run(*args, **kwargs):
        if flow_run_repo.get.await_count == 1:
            return queued_run
        return running_run

    flow_run_repo.get = AsyncMock(side_effect=_get_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "http_post",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="result",
            persisted_text="result",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=11,
            effective_prompt="prompt",
            model_parameters_json={"temperature": 0.2},
        )
    )
    executor._deliver_webhook = AsyncMock(
        side_effect=RuntimeError("webhook unavailable")
    )
    log_exception = MagicMock()
    monkeypatch.setattr("intric.flows.runtime.executor.logger.exception", log_exception)

    await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    log_exception.assert_called_once()
    log_args = log_exception.call_args.args
    assert "flow_executor.webhook_delivery_failed" in log_args[0]
    assert log_args[1] == queued_run.id
    assert log_args[3] == step_id


@pytest.mark.asyncio
async def test_webhook_success_persists_delivery_and_completes_run(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "http_post",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="result",
            persisted_text="result",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=11,
            effective_prompt="prompt",
            model_parameters_json={"temperature": 0.2},
        )
    )
    executor._deliver_webhook = AsyncMock()

    async def _list_step_results(*args, **kwargs):
        if not flow_repo.save_step_result.await_args_list:
            return []
        return [flow_repo.save_step_result.await_args_list[-1].args[1]]

    flow_run_repo.list_step_results = AsyncMock(side_effect=_list_step_results)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "completed"}
    assert flow_repo.save_step_result.await_count == 2
    first_saved = flow_repo.save_step_result.await_args_list[0].args[1]
    second_saved = flow_repo.save_step_result.await_args_list[1].args[1]
    assert first_saved.status == FlowStepResultStatus.COMPLETED
    assert second_saved.status == FlowStepResultStatus.COMPLETED
    assert second_saved.output_payload_json["webhook_delivered"] is True
    assert "webhook_error" not in second_saved.output_payload_json
    executor.flow_run_terminalizer.terminalize_run.assert_awaited()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args_list[-1].kwargs[
            "target_status"
        ]
        == FlowRunStatus.COMPLETED
    )
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args_list[-1].kwargs[
            "output_payload_json"
        ]
        == second_saved.output_payload_json
    )


@pytest.mark.asyncio
async def test_execute_persists_distinct_model_parameters_for_each_step(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    first_step_id = uuid4()
    second_step_id = uuid4()
    first_assistant_id = uuid4()
    second_assistant_id = uuid4()
    first_claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=first_step_id,
        assistant_id=first_assistant_id,
    )
    second_claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=second_step_id,
        assistant_id=second_assistant_id,
    ).model_copy(update={"step_order": 2})

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(
        side_effect=[first_claimed, second_claimed]
    )
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(first_step_id),
                        "step_order": 1,
                        "assistant_id": str(first_assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(second_step_id),
                        "step_order": 2,
                        "assistant_id": str(second_assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        side_effect=[
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                legacy_prompt_binding_used=False,
                full_text="step-one",
                persisted_text="step-one",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=11,
                effective_prompt="prompt-one",
                model_parameters_json={
                    "model_id": str(uuid4()),
                    "model_name": "claude-haiku-4-5",
                    "provider": "anthropic",
                },
            ),
            StepExecutionOutput(
                input_text="step-one",
                source_text="step-one",
                input_source="previous_step",
                used_question_binding=False,
                legacy_prompt_binding_used=False,
                full_text="step-two",
                persisted_text="step-two",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=12,
                num_tokens_output=13,
                effective_prompt="prompt-two",
                model_parameters_json={
                    "model_id": str(uuid4()),
                    "model_name": "gpt-4o-mini",
                    "provider": "openai",
                },
            ),
        ]
    )

    async def _list_step_results(*args, **kwargs):
        return [call.args[1] for call in flow_repo.save_step_result.await_args_list]

    flow_run_repo.list_step_results = AsyncMock(side_effect=_list_step_results)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "completed"}
    assert flow_repo.save_step_result.await_count == 2
    first_saved = flow_repo.save_step_result.await_args_list[0].args[1]
    second_saved = flow_repo.save_step_result.await_args_list[1].args[1]
    assert first_saved.model_parameters_json == {
        "model_id": first_saved.model_parameters_json["model_id"],
        "model_name": "claude-haiku-4-5",
        "provider": "anthropic",
    }
    assert second_saved.model_parameters_json == {
        "model_id": second_saved.model_parameters_json["model_id"],
        "model_name": "gpt-4o-mini",
        "provider": "openai",
    }


@pytest.mark.asyncio
async def test_deliver_webhook_uses_interpolated_url_and_body_template(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="http_post",
        output_config={
            "url": "https://example.org/hook/{{flow_input.id}}",
            "timeout_seconds": 9,
            "body_template": '{"result":"{{text}}"}',
        },
        output_type="text",
    )
    run = run.model_copy(update={"input_payload_json": {"id": "abc-123"}})
    request = httpx.Request("POST", "https://example.org/hook/abc-123")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request)
    )

    await executor._deliver_webhook(
        step=step,
        text_payload="done",
        run=run,
        context={"flow_input": {"id": "abc-123"}, "text": "done"},
    )

    executor._send_http_request.assert_awaited_once()
    kwargs = executor._send_http_request.await_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "https://example.org/hook/abc-123"
    assert kwargs["timeout_seconds"] == 9
    assert kwargs["body_bytes"] == b'{"result":"done"}'
    assert kwargs["read_response_body"] is False
    assert kwargs["headers"]["Idempotency-Key"]


@pytest.mark.asyncio
async def test_deliver_webhook_uses_interpolated_body_json_and_headers(user):
    executor, _, _, _ = _build_executor(user)
    executor.encryption_service.is_encrypted = MagicMock(return_value=False)
    executor.encryption_service.decrypt = MagicMock(side_effect=lambda value: value)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=2,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="http_post",
        output_config={
            "url": "https://example.org/hook/{{flow_input.case_id}}",
            "headers": {"X-Case-Id": "{{flow_input.case_id}}"},
            "body_json": {
                "result": "{{text}}",
                "case_id": "{{flow_input.case_id}}",
            },
        },
        output_type="text",
    )
    request = httpx.Request("POST", "https://example.org/hook/777")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request)
    )

    await executor._deliver_webhook(
        step=step,
        text_payload='Svar med "citat" och åäö',
        run=run,
        context={
            "flow_input": {"case_id": "777"},
            "text": 'Svar med "citat" och åäö',
        },
    )

    executor._send_http_request.assert_awaited_once()
    kwargs = executor._send_http_request.await_args.kwargs
    assert kwargs["url"] == "https://example.org/hook/777"
    assert kwargs["headers"]["X-Case-Id"] == "777"
    assert kwargs["body_bytes"] is None
    assert kwargs["read_response_body"] is False
    assert kwargs["json_body"] == {
        "result": 'Svar med "citat" och åäö',
        "case_id": 777,
    }


@pytest.mark.asyncio
async def test_deliver_webhook_rejects_conflicting_body_template_and_body_json(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="http_post",
        output_config={
            "url": "https://example.org/hook",
            "body_template": '{"result":"{{text}}"}',
            "body_json": {"result": "{{text}}"},
        },
        output_type="text",
    )

    with pytest.raises(
        TypedIOValidationException,
        match="cannot define both body_template and body_json",
    ):
        await executor._deliver_webhook(
            step=step,
            text_payload="done",
            run=run,
            context={"flow_input": {}, "text": "done"},
        )


@pytest.mark.asyncio
async def test_deliver_webhook_ssrf_blocked_url_raises_bad_request(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="http_post",
        output_config={"url": "http://127.0.0.1/hook"},
        output_type="text",
    )

    with pytest.raises(BadRequestException, match="SSRF"):
        await executor._deliver_webhook(
            step=step,
            text_payload="done",
            run=run,
            context={"text": "done", "flow_input": {}},
        )


@pytest.mark.asyncio
async def test_deliver_webhook_timeout_raises_bad_request(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="http_post",
        output_config={"url": "https://example.org/hook"},
        output_type="text",
    )
    executor._send_http_request = AsyncMock(
        side_effect=httpx.TimeoutException("timeout")
    )

    with pytest.raises(BadRequestException, match="timed out"):
        await executor._deliver_webhook(
            step=step,
            text_payload="done",
            run=run,
            context={"text": "done", "flow_input": {}},
        )


@pytest.mark.asyncio
async def test_duplicate_worker_exits_when_step_already_claimed(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    running_step = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=running_step)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "step_already_claimed"}


@pytest.mark.asyncio
async def test_execute_skips_when_run_claim_fails(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=False)
    executor._execute_step = AsyncMock()

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_running"}
    executor._execute_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_short_circuits_terminal_run_without_lifecycle_writes(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    completed_run = _run(status=FlowRunStatus.COMPLETED, user=user)

    flow_run_repo.get = AsyncMock(return_value=completed_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock()
    flow_run_repo.claim_step_result = AsyncMock()

    result = await executor.execute(
        run_id=completed_run.id,
        flow_id=completed_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_terminal"}
    flow_run_repo.mark_running_if_claimable.assert_not_awaited()
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor.flow_run_terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_cancels_when_flow_deleted_before_step_execution(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    executor._flow_is_active = AsyncMock(return_value=False)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "cancelled", "reason": "flow_deleted"}
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs["source"]
        == FlowRunTerminalSource.FLOW_DELETED
    )


@pytest.mark.asyncio
async def test_step_execution_failure_marks_attempt_and_run_failed(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(side_effect=RuntimeError("llm boom"))

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result["status"] == "failed"
    assert result["error"] == "step_execution_failed"
    flow_run_repo.finish_attempt.assert_awaited_once()
    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["status"] == FlowStepAttemptStatus.FAILED
    assert finish_kwargs["error_code"] == "step_execution_failed"
    assert finish_kwargs["error_message"] == "Flow step 1 execution failed."
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    update_kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert update_kwargs["error_message"] == "Flow step 1 execution failed."
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.error_message == "Flow step 1 execution failed."


@pytest.mark.asyncio
async def test_attempt_start_failure_after_claim_marks_run_and_step_failed(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock(
        side_effect=RuntimeError("db write failed")
    )
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "error": "step_execution_failed"}
    flow_run_repo.finish_attempt.assert_not_awaited()
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.error_message == "Flow step 1 execution failed."
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.FAILED
    )


@pytest.mark.asyncio
async def test_typed_validation_failure_persists_input_context_for_export(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    typed_exc = TypedIOValidationException(
        "Step 1 input: 'not json' is not of type 'object'",
        code="typed_io_contract_violation",
    )
    typed_exc.input_payload_json = {
        "text": "not json",
        "source_text": "not json",
        "input_source": "flow_input",
        "contract_validation": {
            "schema_type_hint": "object",
            "parse_attempted": True,
            "parse_succeeded": False,
            "candidate_type": "str",
        },
    }
    typed_exc.effective_prompt = "Categorize this"
    executor._execute_step = AsyncMock(side_effect=typed_exc)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result["status"] == "failed"
    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["status"] == FlowStepAttemptStatus.FAILED
    assert finish_kwargs["error_code"] == "typed_io_contract_violation"
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.input_payload_json == typed_exc.input_payload_json
    assert saved_result.effective_prompt == "Categorize this"


@pytest.mark.asyncio
async def test_typed_validation_failure_without_attached_context_uses_fallback_payload(
    user,
):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        side_effect=TypedIOValidationException(
            "Step 1 output: expected object",
            code="typed_io_contract_violation",
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result["status"] == "failed"
    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["status"] == FlowStepAttemptStatus.FAILED
    assert finish_kwargs["error_code"] == "typed_io_contract_violation"
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.input_payload_json == {
        "text": "",
        "source_text": "",
        "input_source": "flow_input",
        "used_question_binding": False,
        "legacy_prompt_binding_used": False,
    }


@pytest.mark.asyncio
async def test_apply_output_cap_persists_file_when_over_limit(user):
    executor, _, _, _ = _build_executor(user)
    executor.max_inline_text_bytes = 5
    file_id = uuid4()
    executor.file_repo.add = AsyncMock(return_value=SimpleNamespace(id=file_id))
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = SimpleNamespace(step_order=1)
    long_text = "abcdefghi"

    persisted_text, file_ids = await executor._apply_output_cap(
        text=long_text,
        run=run,
        step=step,
    )

    assert persisted_text == long_text[:4096]
    assert file_ids == [file_id]
    executor.file_repo.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_output_cap_handles_utf8_byte_limit(user):
    executor, _, _, _ = _build_executor(user)
    executor.max_inline_text_bytes = 5
    run = _run(status=FlowRunStatus.RUNNING, user=user).model_copy(
        update={"user_id": None}
    )
    step = SimpleNamespace(step_order=1)
    utf8_text = "ååå"  # 6 bytes in UTF-8, exceeds 5-byte cap.

    persisted_text, file_ids = await executor._apply_output_cap(
        text=utf8_text,
        run=run,
        step=step,
    )

    assert persisted_text == utf8_text[:4096]
    assert file_ids == []


@pytest.mark.asyncio
async def test_execute_marks_run_completed_with_last_completed_output_payload(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    existing = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    ).model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "final"},
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=existing)
    flow_run_repo.list_step_results = AsyncMock(return_value=[existing])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "completed"}
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert kwargs["target_status"] == FlowRunStatus.COMPLETED
    assert kwargs["output_payload_json"] == {"text": "final"}


@pytest.mark.asyncio
async def test_execute_returns_cancelled_when_any_step_result_cancelled(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    existing = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    ).model_copy(
        update={"status": FlowStepResultStatus.COMPLETED},
        deep=True,
    )
    cancelled_result = existing.model_copy(
        update={
            "status": FlowStepResultStatus.CANCELLED,
            "error_message": "cancelled by policy",
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=existing)
    flow_run_repo.list_step_results = AsyncMock(return_value=[cancelled_result])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "cancelled"}
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.CANCELLED
    )


@pytest.mark.asyncio
async def test_execute_returns_run_in_progress_when_pending_results_exist(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    existing = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    ).model_copy(
        update={"status": FlowStepResultStatus.COMPLETED},
        deep=True,
    )
    pending_result = existing.model_copy(
        update={"status": FlowStepResultStatus.PENDING},
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=existing)
    flow_run_repo.list_step_results = AsyncMock(return_value=[pending_result])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_in_progress"}
    executor.flow_run_terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_uses_retry_count_plus_one_for_attempt_lifecycle(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )
    completed = claimed.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "done"},
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.list_step_results = AsyncMock(side_effect=[[], [completed]])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="done",
            persisted_text="done",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=10,
            effective_prompt="prompt",
            model_parameters_json={},
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=2,
    )

    assert result == {"status": "completed"}
    assert (
        flow_run_repo.create_or_get_attempt_started.await_args.kwargs["attempt_no"] == 3
    )
    assert flow_run_repo.finish_attempt.await_args.kwargs["attempt_no"] == 3


@pytest.mark.asyncio
async def test_execute_stops_before_claiming_later_steps_when_run_becomes_cancelled(
    user,
):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    cancelled_run = queued_run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    step_id_1 = uuid4()
    step_id_2 = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_1,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, cancelled_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id_1),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(step_id_2),
                        "step_order": 2,
                        "assistant_id": str(assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="step-one",
            persisted_text="step-one",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=10,
            effective_prompt="prompt",
            model_parameters_json={},
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_cancelled"}
    assert flow_run_repo.claim_step_result.await_count == 1
    assert flow_run_repo.create_or_get_attempt_started.await_count == 1


@pytest.mark.asyncio
async def test_execute_does_not_persist_step_after_run_cancelled_during_execution(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    cancelled_run = queued_run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run, cancelled_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="result",
            persisted_text="result",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=10,
            effective_prompt="prompt",
            model_parameters_json={},
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_cancelled"}
    flow_repo.save_step_result.assert_not_awaited()
    flow_run_repo.finish_attempt.assert_awaited_once()
    assert (
        flow_run_repo.finish_attempt.await_args.kwargs["status"]
        == FlowStepAttemptStatus.CANCELLED
    )
    executor.flow_run_terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_appends_completed_handoff_and_continues_with_next_step(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id_1 = uuid4()
    step_id_2 = uuid4()
    assistant_id = uuid4()
    existing_completed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_1,
        assistant_id=assistant_id,
    ).model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "from-step-1"},
        },
        deep=True,
    )
    claimed_second = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_2,
        assistant_id=assistant_id,
    )
    completed_second = claimed_second.model_copy(
        update={
            "step_order": 2,
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "from-step-2"},
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(side_effect=[None, claimed_second])
    flow_run_repo.get_step_result = AsyncMock(return_value=existing_completed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.list_step_results = AsyncMock(side_effect=[[], [completed_second]])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id_1),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(step_id_2),
                        "step_order": 2,
                        "assistant_id": str(assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="from-step-1",
            source_text="from-step-1",
            input_source="previous_step",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="from-step-2",
            persisted_text="from-step-2",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=10,
            effective_prompt="prompt",
            model_parameters_json={},
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "completed"}
    flow_run_repo.create_or_get_attempt_started.assert_awaited_once()
    assert (
        flow_run_repo.create_or_get_attempt_started.await_args.kwargs["step_id"]
        == step_id_2
    )
    executor._execute_step.assert_awaited_once()
    assert (
        executor._execute_step.await_args.kwargs["state"].completed_by_order[1]
        == existing_completed
    )


@pytest.mark.asyncio
async def test_execute_cancels_when_flow_deleted_after_first_step_and_keeps_completed_evidence(
    user,
):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id_1 = uuid4()
    step_id_2 = uuid4()
    assistant_id = uuid4()
    claimed_first = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_1,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed_first)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id_1),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(step_id_2),
                        "step_order": 2,
                        "assistant_id": str(assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(side_effect=[True, True, False])
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="step-one",
            persisted_text="step-one",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=10,
            effective_prompt="prompt",
            model_parameters_json={},
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "cancelled", "reason": "flow_deleted"}
    assert flow_repo.save_step_result.await_count >= 1
    first_saved = flow_repo.save_step_result.await_args_list[0].args[1]
    assert first_saved.status == FlowStepResultStatus.COMPLETED
    update_kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert update_kwargs["target_status"] == FlowRunStatus.CANCELLED
    assert update_kwargs["source"] == FlowRunTerminalSource.FLOW_DELETED
    assert update_kwargs["error_message"] == "Flow was deleted during execution."


def _runtime_step(
    *,
    step_order: int,
    input_source: str,
    input_bindings: dict[str, object] | None = None,
) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=None,
        input_source=input_source,
        input_bindings=input_bindings,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )


def _completed_step_result(
    *,
    run_id,
    flow_id,
    tenant_id,
    step_order: int,
    text: str,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json={"text": f"input-{step_order}"},
        effective_prompt="prompt",
        output_payload_json={"text": text},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash="hash",
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_resolve_step_input_previous_step_prefers_source_text_over_legacy_text_binding(
    user,
):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="HELLO WORLD",
        )
    ]
    step = _runtime_step(
        step_order=2,
        input_source="previous_step",
        input_bindings={"text": "legacy {{flow_input.text}}"},
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert resolved.text == "HELLO WORLD"
    assert resolved.used_question_binding is False
    assert resolved.legacy_prompt_binding_used is True
    assert resolved.input_source == "previous_step"


@pytest.mark.asyncio
async def test_resolve_step_input_all_previous_steps_prefers_aggregated_source_text(
    user,
):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="ONE",
        ),
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=2,
            text="TWO",
        ),
    ]
    step = _runtime_step(
        step_order=3,
        input_source="all_previous_steps",
        input_bindings={"text": "legacy override"},
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert "<step_1_output>\nONE\n</step_1_output>" in resolved.text
    assert "<step_2_output>\nTWO\n</step_2_output>" in resolved.text
    assert resolved.used_question_binding is False
    assert resolved.legacy_prompt_binding_used is True
    assert resolved.input_source == "all_previous_steps"


@pytest.mark.asyncio
async def test_resolve_step_input_question_binding_overrides_source_text(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="HELLO WORLD",
        )
    ]
    step = _runtime_step(
        step_order=2,
        input_source="previous_step",
        input_bindings={
            "question": "Summarize: {{step_1.output.text}}",
            "text": "legacy",
        },
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert resolved.text == "Summarize: HELLO WORLD"
    assert resolved.used_question_binding is True
    assert resolved.legacy_prompt_binding_used is True


@pytest.mark.asyncio
async def test_resolve_step_input_legacy_mirrored_question_binding_uses_source_text(
    user,
):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="HELLO WORLD",
        )
    ]
    step = _runtime_step(
        step_order=2,
        input_source="previous_step",
        input_bindings={
            "question": "Du ska alltid konvertera texten till stora bokstäver"
        },
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
        assistant_prompt_text="Du ska alltid konvertera texten till stora bokstäver",
    )

    assert resolved.text == "HELLO WORLD"
    assert resolved.used_question_binding is False
    assert resolved.legacy_prompt_binding_used is True


@pytest.mark.asyncio
async def test_resolve_step_input_raises_for_unknown_source(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(step_order=1, input_source="unknown_source")

    with pytest.raises(BadRequestException, match="Unsupported input source"):
        await executor._resolve_step_input(
            step=step,
            context={},
            run=run,
            prior_results=[],
        )


@pytest.mark.asyncio
async def test_execute_fails_run_when_claimed_step_result_missing(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=None)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "error": "step_missing"}
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.FAILED
    )


@pytest.mark.asyncio
async def test_execute_fails_run_when_definition_snapshot_is_invalid(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "error": "invalid_flow_definition"}
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.FAILED
    )


def test_parse_runtime_steps_rejects_invalid_output_mode(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(BadRequestException, match="Unsupported output mode"):
        executor._parse_runtime_steps(
            {
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "output_mode": "invalid_mode",
                    }
                ]
            }
        )


def test_parse_runtime_steps_rejects_invalid_input_type(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(BadRequestException, match="Unsupported input type"):
        executor._parse_runtime_steps(
            {
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "input_type": "banana",
                        "output_mode": "pass_through",
                    }
                ]
            }
        )


def test_parse_runtime_steps_rejects_invalid_output_type(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(BadRequestException, match="Unsupported output type"):
        executor._parse_runtime_steps(
            {
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                        "output_type": "banana",
                    }
                ]
            }
        )


def test_parse_runtime_steps_accepts_transcribe_only_output_mode(user):
    executor, _, _, _ = _build_executor(user)

    parsed = executor._parse_runtime_steps(
        {
            "steps": [
                {
                    "step_id": str(uuid4()),
                    "step_order": 1,
                    "assistant_id": str(uuid4()),
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_type": "text",
                    "output_mode": "transcribe_only",
                }
            ]
        }
    )

    assert len(parsed) == 1
    assert parsed[0].output_mode == "transcribe_only"


def test_parse_runtime_steps_rejects_non_object_webhook_headers(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(
        BadRequestException, match="output_config.headers must be an object"
    ):
        executor._parse_runtime_steps(
            {
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "output_mode": "http_post",
                        "output_config": {
                            "url": "https://example.org",
                            "headers": "not-an-object",
                        },
                    }
                ]
            }
        )


def test_parse_runtime_steps_rejects_all_previous_steps_json_input(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(
        BadRequestException, match="incompatible with input_source 'all_previous_steps'"
    ):
        executor._parse_runtime_steps(
            {
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_type": "text",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(uuid4()),
                        "step_order": 2,
                        "assistant_id": str(uuid4()),
                        "input_source": "all_previous_steps",
                        "input_type": "json",
                        "output_type": "text",
                        "output_mode": "pass_through",
                    },
                ]
            }
        )


def test_parse_runtime_steps_rejects_incompatible_previous_step_chain(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(BadRequestException, match="incompatible type chain"):
        executor._parse_runtime_steps(
            {
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_type": "docx",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(uuid4()),
                        "step_order": 2,
                        "assistant_id": str(uuid4()),
                        "input_source": "previous_step",
                        "input_type": "json",
                        "output_type": "text",
                        "output_mode": "pass_through",
                    },
                ]
            }
        )


def test_parse_runtime_steps_rejects_duplicate_step_orders(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(BadRequestException, match="Duplicate step_order detected"):
        executor._parse_runtime_steps(
            {
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                ]
            }
        )


def test_parse_runtime_steps_rejects_non_contiguous_step_orders(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(
        BadRequestException, match="Step order must be contiguous and start at 1"
    ):
        executor._parse_runtime_steps(
            {
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(uuid4()),
                        "step_order": 3,
                        "assistant_id": str(uuid4()),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            }
        )


# --- RunExecutionState ---


def test_run_execution_state_append_completed():
    """append_completed tracks results and builds accumulated text."""
    now = datetime.now(timezone.utc)
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt="",
        output_payload_json={"text": "hello"},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash="h",
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )
    state.append_completed(result)

    assert 1 in state.completed_by_order
    assert len(state.prior_results) == 1
    assert "<step_1_output>" in state.all_previous_text
    assert "hello" in state.all_previous_text


def test_run_execution_state_all_previous_text_accumulates():
    """Multiple appends build up all_previous_text correctly."""
    now = datetime.now(timezone.utc)
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    for order, text in [(1, "first"), (2, "second")]:
        result = FlowStepResult(
            id=uuid4(),
            flow_run_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            step_id=uuid4(),
            step_order=order,
            assistant_id=uuid4(),
            input_payload_json={},
            effective_prompt="",
            output_payload_json={"text": text},
            model_parameters_json={},
            num_tokens_input=1,
            num_tokens_output=1,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            flow_step_execution_hash="h",
            tool_calls_metadata=None,
            created_at=now,
            updated_at=now,
        )
        state.append_completed(result)

    assert "<step_1_output>" in state.all_previous_text
    assert "<step_2_output>" in state.all_previous_text
    assert "first" in state.all_previous_text
    assert "second" in state.all_previous_text


# --- Assistant cache ---


@pytest.mark.asyncio
async def test_assistant_cache_hit(user):
    """Same assistant ID loaded twice — get_space_by_assistant called once."""
    executor, _, _, _ = _build_executor(user)
    assistant_id = uuid4()
    mock_assistant = SimpleNamespace(id=assistant_id)
    mock_space = SimpleNamespace(get_assistant=lambda assistant_id: mock_assistant)
    executor.space_repo.get_space_by_assistant = AsyncMock(return_value=mock_space)

    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )

    result1 = await executor._load_assistant(assistant_id, state)
    result2 = await executor._load_assistant(assistant_id, state)

    assert result1 is result2
    assert executor.space_repo.get_space_by_assistant.call_count == 1


def _step_for_execute_step(*, step_order: int = 1) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        output_type="text",
        input_type="text",
    )


def _assistant_for_snapshot(
    *,
    assistant_id,
    model_id,
    prompt: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=assistant_id,
        origin="flow_managed",
        prompt=SimpleNamespace(text=prompt),
        completion_model=SimpleNamespace(
            id=model_id,
            name="gpt-5.4-nano",
            nickname="Nano",
            litellm_model_name="openai/gpt-5.4-nano",
        ),
        completion_model_kwargs={"temperature": 0.2},
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        mcp_servers=[],
    )


@pytest.mark.asyncio
async def test_validate_assistant_snapshots_accepts_matching_execution_surface(user):
    executor, _, _, _ = _build_executor(user)
    assistant_id = uuid4()
    model_id = uuid4()
    assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case.",
    )
    snapshot = build_assistant_execution_snapshot(
        assistant=assistant,
        mcp_server_entities=[],
    )
    assert snapshot is not None
    step = replace(
        _step_for_execute_step(),
        assistant_id=assistant_id,
        assistant_snapshot=snapshot,
    )
    state = _empty_execution_state()
    executor._load_assistant = AsyncMock(return_value=assistant)

    await executor._validate_assistant_snapshots(
        steps=[step],
        state=state,
        run_id=uuid4(),
    )

    executor._load_assistant.assert_awaited_once_with(assistant_id, state)


@pytest.mark.asyncio
async def test_validate_assistant_snapshots_rejects_prompt_drift(user):
    executor, _, _, _ = _build_executor(user)
    assistant_id = uuid4()
    model_id = uuid4()
    published_assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case.",
    )
    current_assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case and make recommendations.",
    )
    snapshot = build_assistant_execution_snapshot(
        assistant=published_assistant,
        mcp_server_entities=[],
    )
    assert snapshot is not None
    step = replace(
        _step_for_execute_step(),
        assistant_id=assistant_id,
        assistant_snapshot=snapshot,
    )
    executor._load_assistant = AsyncMock(return_value=current_assistant)

    with pytest.raises(BadRequestException, match="changed after publish"):
        await executor._validate_assistant_snapshots(
            steps=[step],
            state=_empty_execution_state(),
            run_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_validate_assistant_snapshots_skips_legacy_steps_without_snapshot(user):
    executor, _, _, _ = _build_executor(user)
    executor._load_assistant = AsyncMock()

    await executor._validate_assistant_snapshots(
        steps=[_step_for_execute_step()],
        state=_empty_execution_state(),
        run_id=uuid4(),
    )

    executor._load_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_assistant_snapshots_requires_schema_versioned_snapshots(user):
    executor, _, _, _ = _build_executor(user)
    executor._load_assistant = AsyncMock()

    with pytest.raises(BadRequestException, match="snapshot is missing"):
        await executor._validate_assistant_snapshots(
            steps=[_step_for_execute_step()],
            state=_empty_execution_state(),
            run_id=uuid4(),
            require_snapshots=True,
        )

    executor._load_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_step_uses_rag_chunks_when_knowledge_present(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=(None, None))
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    source_id = uuid4()
    chunks = [
        SimpleNamespace(
            info_blob_id=source_id,
            info_blob_title="Finance update",
            chunk_no=1,
            score=0.91,
            text="Sundsvalls kommun redovisar ett positivt resultat för 2025.",
        ),
        SimpleNamespace(
            info_blob_id=source_id,
            info_blob_title="Finance update",
            chunk_no=2,
            score=0.77,
            text="I november låg prognosen på lägre nivå men utfallet förbättrades.",
        ),
    ]
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock(
        return_value=SimpleNamespace(chunks=chunks, no_duplicate_chunks=[chunks[0]])
    )

    output = await executor._execute_step(step=step, run=run, state=state)

    executor.references_service.get_references.assert_awaited_once()
    rag_kwargs = executor.references_service.get_references.await_args.kwargs
    assert rag_kwargs["version"] == 1
    assert rag_kwargs["include_info_blobs"] is False
    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == chunks
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "success"
    assert output.rag_metadata["chunks_retrieved"] == 2
    assert output.rag_metadata["raw_chunks_count"] == 2
    assert output.rag_metadata["deduped_chunks_count"] == 1
    assert output.rag_metadata["attempted"] is True
    assert output.rag_metadata["retrieval_duration_ms"] is not None
    assert output.rag_metadata["retrieval_error_type"] is None
    assert output.rag_metadata["references_truncated"] is False
    assert len(output.rag_metadata["references"]) == 1
    assert output.rag_metadata["references"][0]["id"] == str(source_id)
    assert output.rag_metadata["references"][0]["matched_chunk_count"] == 2
    assert output.rag_metadata["references"][0]["best_score"] == pytest.approx(0.91)
    assert len(output.rag_metadata["references"][0]["chunks"]) == 2


@pytest.mark.asyncio
async def test_execute_step_skips_rag_when_assistant_has_no_knowledge(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=False)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=(None, None))
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock()

    output = await executor._execute_step(step=step, run=run, state=state)

    executor.references_service.get_references.assert_not_awaited()
    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == []
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "skipped_no_knowledge"
    assert output.rag_metadata["attempted"] is False


@pytest.mark.asyncio
async def test_execute_step_rag_timeout_appends_diagnostic_and_continues(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=(None, None))
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock(
        side_effect=asyncio.TimeoutError()
    )

    output = await executor._execute_step(step=step, run=run, state=state)

    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == []
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "timeout"
    assert output.rag_metadata["error_code"] == "rag_retrieval_timeout"
    assert output.rag_metadata["retrieval_error_type"] == "TimeoutError"
    assert any(d.code == "rag_retrieval_timeout" for d in output.diagnostics)


@pytest.mark.asyncio
async def test_execute_step_rag_failure_appends_diagnostic_and_continues(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=(None, None))
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    output = await executor._execute_step(step=step, run=run, state=state)

    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == []
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "error"
    assert output.rag_metadata["error_code"] == "rag_retrieval_failed"
    assert output.rag_metadata["retrieval_error_type"] == "RuntimeError"
    assert any(d.code == "rag_retrieval_failed" for d in output.diagnostics)


@pytest.mark.asyncio
async def test_execute_step_skips_rag_when_input_is_whitespace(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="   ", source_text="   ", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=(None, None))
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock()

    output = await executor._execute_step(step=step, run=run, state=state)

    executor.references_service.get_references.assert_not_awaited()
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "skipped_no_input"
    assert output.rag_metadata["attempted"] is False


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_caps_sources_and_chunks(user):
    executor, _, _, _ = _build_executor(user)
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor.references_service = AsyncMock()

    chunks = []
    for source_index in range(27):
        source_id = uuid4()
        for chunk_index in range(7):
            chunks.append(
                SimpleNamespace(
                    info_blob_id=source_id,
                    info_blob_title=f"Source {source_index}",
                    chunk_no=chunk_index + 1,
                    score=1.0 - (chunk_index * 0.01),
                    text=f"Chunk {chunk_index} from source {source_index} " * 8,
                )
            )

    executor.references_service.get_references = AsyncMock(
        return_value=SimpleNamespace(chunks=chunks, no_duplicate_chunks=chunks[:27])
    )

    _, metadata, diagnostics = await executor._retrieve_rag_chunks(
        assistant=assistant,
        question="what happened?",
        run_id=uuid4(),
        step_order=1,
    )

    assert diagnostics == []
    assert metadata["status"] == "success"
    assert metadata["references_truncated"] is True
    assert len(metadata["references"]) == 25
    assert metadata["raw_chunks_count"] == len(chunks)
    assert metadata["deduped_chunks_count"] == 27
    assert all(len(reference["chunks"]) <= 5 for reference in metadata["references"])


# --- Prior results bootstrap ---


@pytest.mark.asyncio
async def test_prior_results_bootstrap_once(user):
    """list_step_results called exactly once at bootstrap, not per step."""
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id_1, step_id_2 = uuid4(), uuid4()
    assistant_id = uuid4()

    claimed_1 = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_1,
        assistant_id=assistant_id,
    )
    claimed_2 = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_2,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(side_effect=[claimed_1, claimed_2])
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    # Bootstrap call returns empty (fresh run), final call returns all completed
    completed_1 = claimed_1.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "out1"},
        },
        deep=True,
    )
    completed_2 = claimed_2.model_copy(
        update={
            "step_order": 2,
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "out2"},
        },
        deep=True,
    )
    flow_run_repo.list_step_results = AsyncMock(
        side_effect=[
            [],  # bootstrap
            [completed_1, completed_2],  # final check
        ]
    )
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id_1),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(step_id_2),
                        "step_order": 2,
                        "assistant_id": str(assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="result",
            persisted_text="result",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=11,
            effective_prompt="prompt",
            model_parameters_json={"temperature": 0.2},
        )
    )

    await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    # list_step_results: 1 bootstrap + 1 final = 2 total (NOT per-step)
    assert flow_run_repo.list_step_results.call_count == 2


@pytest.mark.asyncio
async def test_execute_fails_before_claim_when_assistant_snapshot_drifted(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    assistant_id = uuid4()
    model_id = uuid4()
    published_assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case.",
    )
    current_assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case and include recommendations.",
    )
    snapshot = build_assistant_execution_snapshot(
        assistant=published_assistant,
        mcp_server_entities=[],
    )
    assert snapshot is not None
    step_id = uuid4()

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.list_step_results = AsyncMock(return_value=[])
    flow_run_repo.claim_step_result = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                        "assistant_snapshot": snapshot,
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._load_assistant = AsyncMock(return_value=current_assistant)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "error": "assistant_snapshot_drift"}
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.FAILED
    )


@pytest.mark.asyncio
async def test_execute_fails_before_parse_when_definition_checksum_drifted(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    step_id = uuid4()
    assistant_id = uuid4()

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.list_step_results = AsyncMock()
    flow_run_repo.claim_step_result = AsyncMock()
    executor._parse_runtime_steps = MagicMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum=stable_hash({"steps": []}),
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "error": "definition_checksum_mismatch"}
    executor._parse_runtime_steps.assert_not_called()
    flow_run_repo.list_step_results.assert_not_awaited()
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_fails_before_claim_when_schema_versioned_snapshot_missing(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    step_id = uuid4()
    assistant_id = uuid4()

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.list_step_results = AsyncMock(return_value=[])
    flow_run_repo.claim_step_result = AsyncMock()
    executor._load_assistant = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "schema_version": 1,
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ],
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "error": "assistant_snapshot_drift"}
    executor._load_assistant.assert_not_awaited()
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()


# --- File cache ---


@pytest.mark.asyncio
async def test_file_cache_hit(user):
    """Same file_ids resolved twice — get_list_by_id_and_user called once."""
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    fake_file = SimpleNamespace(id=file_id, text="doc text")
    executor.file_repo.get_list_by_id_and_user = AsyncMock(return_value=[fake_file])

    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )

    run = _run(status=FlowRunStatus.RUNNING, user=user)
    run = run.model_copy(
        update={"input_payload_json": {"text": "x", "file_ids": [str(file_id)]}}
    )
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        input_type="document",
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    await executor._resolve_step_input(
        step=step, context=context, run=run, prior_results=[], state=state
    )
    await executor._resolve_step_input(
        step=step, context=context, run=run, prior_results=[], state=state
    )

    assert executor.file_repo.get_list_by_id_and_user.call_count == 1


# --- Audit logging tests for webhook delivery ---


def _make_audit_service():
    audit_service = AsyncMock()
    audit_service.log_async = AsyncMock(return_value=None)
    return audit_service


@pytest.mark.asyncio
async def test_deliver_webhook_audit_logged_on_success(user):
    audit_service = _make_audit_service()
    executor, _, _, _ = _build_executor(user)
    executor.audit_service = audit_service
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description="Send result",
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="http_post",
        output_config={"url": "https://user:pass@example.org/hook/abc?key=secret"},
        output_type="text",
    )
    request = httpx.Request("POST", "https://example.org/hook/abc")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request)
    )

    await executor._deliver_webhook(
        step=step,
        text_payload="done",
        run=run,
        context={"text": "done"},
    )

    audit_service.log_async.assert_awaited_once()
    call_kwargs = audit_service.log_async.await_args.kwargs
    assert call_kwargs["action"] == ActionType.FLOW_HTTP_OUTBOUND_CALL
    assert call_kwargs["outcome"] == Outcome.SUCCESS
    extra = call_kwargs["metadata"]["extra"]
    assert extra["call_type"] == "webhook_delivery"
    assert extra["http_method"] == "POST"
    assert extra["status_code"] == 200
    assert "duration_ms" in extra
    # URL sanitization: no query params or userinfo leaked
    assert "key=secret" not in extra["url_host"]
    assert "key=secret" not in extra["url_path"]
    assert "pass" not in extra["url_host"]


@pytest.mark.asyncio
async def test_deliver_webhook_audit_logged_on_failure(user):
    audit_service = _make_audit_service()
    executor, _, _, _ = _build_executor(user)
    executor.audit_service = audit_service
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="http_post",
        output_config={"url": "https://example.org/hook"},
        output_type="text",
    )
    executor._send_http_request = AsyncMock(
        side_effect=httpx.TimeoutException("timeout")
    )

    with pytest.raises(BadRequestException, match="timed out"):
        await executor._deliver_webhook(
            step=step,
            text_payload="done",
            run=run,
            context={"text": "done"},
        )

    audit_service.log_async.assert_awaited_once()
    call_kwargs = audit_service.log_async.await_args.kwargs
    assert call_kwargs["action"] == ActionType.FLOW_HTTP_OUTBOUND_CALL
    assert call_kwargs["outcome"] == Outcome.FAILURE
    assert call_kwargs["error_message"] is not None


@pytest.mark.asyncio
async def test_audit_service_failure_does_not_break_webhook(user):
    audit_service = _make_audit_service()
    audit_service.log_async = AsyncMock(side_effect=RuntimeError("audit down"))
    executor, _, _, _ = _build_executor(user)
    executor.audit_service = audit_service
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="http_post",
        output_config={"url": "https://example.org/hook"},
        output_type="text",
    )
    request = httpx.Request("POST", "https://example.org/hook")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request)
    )

    # Should NOT raise despite audit failure
    await executor._deliver_webhook(
        step=step,
        text_payload="done",
        run=run,
        context={"text": "done"},
    )


@pytest.mark.asyncio
async def test_execute_audits_completed_run_terminal_state(user):
    audit_service = _make_audit_service()
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    executor.audit_service = audit_service
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )
    completed_result = claimed.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "done"},
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.list_step_results = AsyncMock(return_value=[completed_result])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="done",
            persisted_text="done",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=10,
            num_tokens_output=10,
            effective_prompt="prompt",
            model_parameters_json={},
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "completed"}
    audit_service.log_async.assert_not_awaited()
    terminal_kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert terminal_kwargs["target_status"] == FlowRunStatus.COMPLETED
    assert terminal_kwargs["source"] == FlowRunTerminalSource.EXECUTOR_COMPLETED


@pytest.mark.asyncio
async def test_execute_audits_failed_run_terminal_state(user):
    audit_service = _make_audit_service()
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    executor.audit_service = audit_service
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(side_effect=RuntimeError("boom"))

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "error": "step_execution_failed"}
    audit_service.log_async.assert_not_awaited()
    terminal_kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert terminal_kwargs["target_status"] == FlowRunStatus.FAILED
    assert terminal_kwargs["source"] == FlowRunTerminalSource.EXECUTOR_FAILED


# --- Encrypted header tests for webhook delivery ---


@pytest.mark.asyncio
async def test_deliver_webhook_decrypts_encrypted_headers(user):
    executor, _, _, _ = _build_executor(user)
    executor.encryption_service.is_encrypted = MagicMock(
        side_effect=lambda v: v.startswith("enc:")
    )
    executor.encryption_service.decrypt = MagicMock(
        side_effect=lambda v: v[len("enc:") :]
    )
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="http_post",
        output_config={
            "url": "https://example.org/hook",
            "headers": {"Authorization": "enc:Bearer secret123", "X-Plain": "visible"},
        },
        output_type="text",
    )
    request = httpx.Request("POST", "https://example.org/hook")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request)
    )

    await executor._deliver_webhook(
        step=step,
        text_payload="done",
        run=run,
        context={"text": "done"},
    )

    executor._send_http_request.assert_awaited_once()
    headers = executor._send_http_request.await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret123"
    assert headers["X-Plain"] == "visible"
    executor.encryption_service.decrypt.assert_called_once_with("enc:Bearer secret123")


@pytest.mark.asyncio
async def test_validate_runtime_step_security_rejects_write_down(user):
    executor, _, _, _ = _build_executor(user)
    assistant_id = uuid4()
    space = SimpleNamespace(security_classification=SimpleNamespace(security_level=1))
    assistant = SimpleNamespace(
        completion_model=SimpleNamespace(
            security_classification=SimpleNamespace(security_level=3)
        ),
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        mcp_servers=[],
    )
    executor.space_repo.get_space_by_assistant = AsyncMock(return_value=space)
    executor._load_assistant = AsyncMock(return_value=assistant)
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=2,
        assistant_id=assistant_id,
        user_description="Step 2",
        input_source="previous_step",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        output_classification_override=1,
    )

    with pytest.raises(BadRequestException, match="output classification override"):
        await executor._validate_runtime_step_security(
            step=step,
            state=state,
            prior_output_levels_by_order={1: 3},
        )
