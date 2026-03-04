from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
    FlowVersion,
)
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.outcome import Outcome
from intric.flows.runtime.executor import (
    FlowRunExecutor,
    RunExecutionState,
    RuntimeStep,
    StepExecutionOutput,
    StepInputValue,
)
from intric.main.exceptions import BadRequestException, TypedIOValidationException


def _run(*, status: FlowRunStatus, user) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=user.id,
        tenant_id=user.tenant_id,
        status=status,
        cancelled_at=None,
        input_payload_json={"text": "hello"},
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _claimed_step_result(*, run_id, flow_id, tenant_id, step_id, assistant_id) -> FlowStepResult:
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


def _build_executor(user):
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
    executor = FlowRunExecutor(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        encryption_service=encryption_service,
        max_inline_text_bytes=1024 * 1024,
    )
    return executor, flow_repo, flow_run_repo, flow_version_repo


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
    assistant.completion_model = SimpleNamespace(id=uuid4(), name="gpt-4o-mini", provider_type="openai")
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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.update_status = AsyncMock()
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
        )
    )
    executor._deliver_webhook = AsyncMock(side_effect=RuntimeError("webhook unavailable"))

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
    executor._send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))

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
    executor._send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))

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
            "body_template": "{\"result\":\"{{text}}\"}",
            "body_json": {"result": "{{text}}"},
        },
        output_type="text",
    )

    with pytest.raises(TypedIOValidationException, match="cannot define both body_template and body_json"):
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
    executor._send_http_request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
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
async def test_execute_cancels_when_flow_deleted_before_step_execution(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.mark_pending_steps_cancelled = AsyncMock()
    flow_run_repo.update_status = AsyncMock()
    executor._flow_is_active = AsyncMock(return_value=False)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "cancelled", "reason": "flow_deleted"}
    flow_run_repo.mark_pending_steps_cancelled.assert_awaited_once()
    flow_run_repo.update_status.assert_awaited_once()


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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.update_status = AsyncMock()
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
    flow_run_repo.finish_attempt.assert_awaited_once()
    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["status"] == FlowStepAttemptStatus.FAILED
    assert finish_kwargs["error_code"] == "step_execution_failed"
    flow_run_repo.update_status.assert_awaited_once()
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.error_message == "llm boom"


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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.update_status = AsyncMock()
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
async def test_typed_validation_failure_without_attached_context_uses_fallback_payload(user):
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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.update_status = AsyncMock()
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
    run = _run(status=FlowRunStatus.RUNNING, user=user).model_copy(update={"user_id": None})
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
            "output_payload_json": {"text": "final", "generated_file_ids": []},
        },
        deep=True,
    )

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=existing)
    flow_run_repo.list_step_results = AsyncMock(return_value=[existing])
    flow_run_repo.update_status = AsyncMock()
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
    flow_run_repo.update_status.assert_awaited_once()
    kwargs = flow_run_repo.update_status.await_args.kwargs
    assert kwargs["status"] == FlowRunStatus.COMPLETED
    assert kwargs["output_payload_json"] == {"text": "final", "generated_file_ids": []}


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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=existing)
    flow_run_repo.list_step_results = AsyncMock(return_value=[cancelled_result])
    flow_run_repo.update_status = AsyncMock()
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
    flow_run_repo.update_status.assert_awaited_once()
    assert flow_run_repo.update_status.await_args.kwargs["status"] == FlowRunStatus.CANCELLED


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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=existing)
    flow_run_repo.list_step_results = AsyncMock(return_value=[pending_result])
    flow_run_repo.update_status = AsyncMock()
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
    flow_run_repo.update_status.assert_not_awaited()


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
async def test_resolve_step_input_previous_step_prefers_source_text_over_legacy_text_binding(user):
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
async def test_resolve_step_input_all_previous_steps_prefers_aggregated_source_text(user):
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
        input_bindings={"question": "Summarize: {{step_1.output.text}}", "text": "legacy"},
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
async def test_resolve_step_input_legacy_mirrored_question_binding_uses_source_text(user):
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
        input_bindings={"question": "Du ska alltid konvertera texten till stora bokstäver"},
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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=None)
    flow_run_repo.update_status = AsyncMock()
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
    flow_run_repo.update_status.assert_awaited_once()
    assert flow_run_repo.update_status.await_args.kwargs["status"] == FlowRunStatus.FAILED


@pytest.mark.asyncio
async def test_execute_fails_run_when_definition_snapshot_is_invalid(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.update_status = AsyncMock()
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
    flow_run_repo.update_status.assert_awaited_once()
    assert flow_run_repo.update_status.await_args.kwargs["status"] == FlowRunStatus.FAILED


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


def test_parse_runtime_steps_rejects_non_object_webhook_headers(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(BadRequestException, match="output_config.headers must be an object"):
        executor._parse_runtime_steps(
            {
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "output_mode": "http_post",
                        "output_config": {"url": "https://example.org", "headers": "not-an-object"},
                    }
                ]
            }
        )


def test_parse_runtime_steps_rejects_all_previous_steps_json_input(user):
    executor, _, _, _ = _build_executor(user)

    with pytest.raises(BadRequestException, match="incompatible with input_source 'all_previous_steps'"):
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
        return_value=StepInputValue(text="hello", source_text="hello", input_source="flow_input")
    )
    executor._process_typed_output = AsyncMock(return_value=(None, None))
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    chunks = [SimpleNamespace(info_blob_id=uuid4()), SimpleNamespace(info_blob_id=uuid4())]
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock(
        return_value=SimpleNamespace(chunks=chunks)
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
    assert output.rag_metadata["attempted"] is True


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
        return_value=StepInputValue(text="hello", source_text="hello", input_source="flow_input")
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
        return_value=StepInputValue(text="hello", source_text="hello", input_source="flow_input")
    )
    executor._process_typed_output = AsyncMock(return_value=(None, None))
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock(side_effect=asyncio.TimeoutError())

    output = await executor._execute_step(step=step, run=run, state=state)

    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == []
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "timeout"
    assert output.rag_metadata["error_code"] == "rag_retrieval_timeout"
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
        return_value=StepInputValue(text="hello", source_text="hello", input_source="flow_input")
    )
    executor._process_typed_output = AsyncMock(return_value=(None, None))
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock(side_effect=RuntimeError("boom"))

    output = await executor._execute_step(step=step, run=run, state=state)

    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == []
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "error"
    assert output.rag_metadata["error_code"] == "rag_retrieval_failed"
    assert any(d.code == "rag_retrieval_failed" for d in output.diagnostics)


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

    flow_run_repo.get = AsyncMock(side_effect=[queued_run, running_run, running_run])
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(side_effect=[claimed_1, claimed_2])
    flow_run_repo.create_or_get_attempt_started = AsyncMock()
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.update_status = AsyncMock()
    # Bootstrap call returns empty (fresh run), final call returns all completed
    completed_1 = claimed_1.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "out1", "generated_file_ids": []},
        },
        deep=True,
    )
    completed_2 = claimed_2.model_copy(
        update={
            "step_order": 2,
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "out2", "generated_file_ids": []},
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
    run = run.model_copy(update={"input_payload_json": {"text": "x", "file_ids": [str(file_id)]}})
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

    await executor._resolve_step_input(step=step, context=context, run=run, prior_results=[], state=state)
    await executor._resolve_step_input(step=step, context=context, run=run, prior_results=[], state=state)

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
    executor._send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))

    await executor._deliver_webhook(
        step=step, text_payload="done", run=run, context={"text": "done"},
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
    executor._send_http_request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with pytest.raises(BadRequestException, match="timed out"):
        await executor._deliver_webhook(
            step=step, text_payload="done", run=run, context={"text": "done"},
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
    executor._send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))

    # Should NOT raise despite audit failure
    await executor._deliver_webhook(
        step=step, text_payload="done", run=run, context={"text": "done"},
    )

    executor._send_http_request.assert_awaited_once()


# --- Encrypted header tests for webhook delivery ---


@pytest.mark.asyncio
async def test_deliver_webhook_decrypts_encrypted_headers(user):
    executor, _, _, _ = _build_executor(user)
    executor.encryption_service.is_encrypted = MagicMock(
        side_effect=lambda v: v.startswith("enc:")
    )
    executor.encryption_service.decrypt = MagicMock(
        side_effect=lambda v: v[len("enc:"):]
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
    executor._send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))

    await executor._deliver_webhook(
        step=step, text_payload="done", run=run, context={"text": "done"},
    )

    executor._send_http_request.assert_awaited_once()
    headers = executor._send_http_request.await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret123"
    assert headers["X-Plain"] == "visible"
    executor.encryption_service.decrypt.assert_called_once_with("enc:Bearer secret123")
