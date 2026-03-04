from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import sqlalchemy as sa

logger = logging.getLogger(__name__)

from intric.ai_models.completion_models.completion_model import Completion
from intric.database.tables.flow_tables import Flows
from intric.files.file_models import FileCreate, FileType
from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from intric.flows.flow_repo import FlowRepository
from intric.flows.flow_run_repo import FlowRunRepository
from intric.flows.flow_version_repo import FlowVersionRepository
from intric.flows.step_config_secrets import decrypt_step_headers_for_runtime
from intric.flows.step_chain_rules import find_first_step_chain_violation
from intric.flows.type_policies import INPUT_TYPE_POLICIES
from intric.flows.variable_resolver import FlowVariableResolver
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, TypedIOValidationException
from intric.settings.encryption_service import EncryptionService
from intric.spaces.space_repo import SpaceRepository
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.files.file_repo import FileRepository
from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome
from intric.audit.application.audit_metadata import AuditMetadata
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService
    from intric.assistants.references import ReferencesService

_TEMPLATE_ONLY_PATTERN = re.compile(r"^\s*\{\{\s*([^{}]+)\s*\}\}\s*$")
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True)
class RuntimeStep:
    step_id: UUID
    step_order: int
    assistant_id: UUID
    user_description: str | None
    input_source: str
    input_bindings: dict[str, Any] | None
    input_config: dict[str, Any] | None
    output_mode: str
    output_config: dict[str, Any] | None
    output_type: str = "text"
    output_contract: dict[str, Any] | None = None
    input_type: str = "text"
    input_contract: dict[str, Any] | None = None


@dataclass(frozen=True)
class StepDiagnostic:
    """Machine-readable diagnostic emitted during step input resolution or execution."""
    code: str
    message: str
    severity: str = "warning"  # "warning" | "info"


@dataclass
class StepExecutionOutput:
    input_text: str
    source_text: str
    input_source: str
    used_question_binding: bool
    legacy_prompt_binding_used: bool
    full_text: str
    persisted_text: str
    generated_file_ids: list[UUID]
    tool_calls_metadata: list[dict[str, Any]] | dict[str, Any] | None
    num_tokens_input: int | None
    num_tokens_output: int | None
    effective_prompt: str
    model_parameters_json: dict[str, Any]
    contract_validation: dict[str, Any] | None = None
    structured_output: dict[str, Any] | list[Any] | None = None
    diagnostics: list[StepDiagnostic] = field(default_factory=list)
    artifacts: list[dict[str, Any]] | None = None
    rag_metadata: dict[str, Any] | None = None


@dataclass
class StepInputValue:
    """Typed step input — carries text, files, or structured data."""
    text: str
    source_text: str = ""
    files: list[Any] | None = None
    structured: dict[str, Any] | list[Any] | None = None
    raw_extracted_text: str = ""
    input_source: str = "flow_input"
    used_question_binding: bool = False
    legacy_prompt_binding_used: bool = False
    diagnostics: list[StepDiagnostic] = field(default_factory=list)


@dataclass(frozen=True)
class StepInputResolution:
    input_text: str
    source_text: str
    input_source: str
    used_question_binding: bool
    legacy_prompt_binding_used: bool


@dataclass
class RunExecutionState:
    """All mutable state for a single flow run execution."""
    completed_by_order: dict[int, FlowStepResult]
    prior_results: list[FlowStepResult]
    all_previous_segments: list[str]
    assistant_cache: dict[UUID, Any]
    json_mode_supported: dict[str, bool]
    file_cache: dict[frozenset[UUID], list[Any]]
    step_names_by_order: dict[int, str] = field(default_factory=dict)

    @property
    def all_previous_text(self) -> str:
        return "".join(self.all_previous_segments)

    def append_completed(self, result: FlowStepResult) -> None:
        self.completed_by_order[result.step_order] = result
        self.prior_results.append(result)
        text = str((result.output_payload_json or {}).get("text", ""))
        self.all_previous_segments.append(
            f"<step_{result.step_order}_output>\n{text}\n</step_{result.step_order}_output>\n"
        )


class FlowRunExecutor:
    """Executes a version-pinned flow run sequentially with CAS step claims."""

    _TERMINAL_STATUSES = {
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
        FlowRunStatus.CANCELLED,
    }
    _ALLOWED_INPUT_SOURCES = {"flow_input", "previous_step", "all_previous_steps", "http_get", "http_post"}
    _ALLOWED_OUTPUT_MODES = {"pass_through", "http_post"}

    def __init__(
        self,
        *,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        flow_version_repo: FlowVersionRepository,
        space_repo: SpaceRepository,
        completion_service: CompletionService,
        file_repo: FileRepository,
        encryption_service: EncryptionService,
        max_inline_text_bytes: int,
        audit_service: AuditService | None = None,
        references_service: ReferencesService | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.flow_version_repo = flow_version_repo
        self.space_repo = space_repo
        self.completion_service = completion_service
        self.file_repo = file_repo
        self.encryption_service = encryption_service
        self.max_inline_text_bytes = max_inline_text_bytes
        self.audit_service = audit_service
        self.references_service = references_service
        self.variable_resolver = FlowVariableResolver()
        settings = get_settings()
        self.http_request_timeout_seconds = float(settings.flow_http_request_timeout_seconds)
        self.http_max_timeout_seconds = float(settings.flow_http_max_timeout_seconds)
        self.http_allow_private_networks = bool(settings.flow_http_allow_private_networks)
        self.rag_retrieval_timeout_seconds = 30

    async def execute(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        celery_task_id: str | None,
        retry_count: int,
    ) -> dict[str, Any]:
        logger.info("flow_executor.start run_id=%s flow_id=%s tenant_id=%s", run_id, flow_id, tenant_id)
        run = await self.flow_run_repo.get(run_id=run_id, tenant_id=tenant_id, flow_id=flow_id)
        if run.status in self._TERMINAL_STATUSES:
            logger.info("flow_executor.skip run_id=%s reason=run_terminal status=%s", run_id, run.status)
            return {"status": "skipped", "reason": "run_terminal"}

        can_run = await self.flow_run_repo.mark_running_if_claimable(
            run_id=run_id,
            tenant_id=tenant_id,
        )
        await self._commit()
        if not can_run:
            latest = await self.flow_run_repo.get(run_id=run_id, tenant_id=tenant_id, flow_id=flow_id)
            return {"status": "skipped", "reason": f"run_{latest.status.value}"}

        if not await self._flow_is_active(flow_id=flow_id, tenant_id=tenant_id):
            reason = "Flow was deleted before execution started."
            await self.flow_run_repo.mark_pending_steps_cancelled(
                run_id=run_id,
                tenant_id=tenant_id,
                error_message=reason,
            )
            await self.flow_run_repo.update_status(
                run_id=run_id,
                tenant_id=tenant_id,
                status=FlowRunStatus.CANCELLED,
                error_message=reason,
                from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
            )
            await self._commit()
            return {"status": "cancelled", "reason": "flow_deleted"}

        version = await self.flow_version_repo.get(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=tenant_id,
        )
        try:
            steps = self._parse_runtime_steps(version.definition_json)
        except BadRequestException as exc:
            await self.flow_run_repo.update_status(
                run_id=run_id,
                tenant_id=tenant_id,
                status=FlowRunStatus.FAILED,
                error_message=str(exc),
                from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
            )
            await self._commit()
            return {"status": "failed", "error": "invalid_flow_definition"}

        # Bootstrap run-scoped state (single DB call for prior results)
        persisted_results = await self.flow_run_repo.list_step_results(run_id=run_id, tenant_id=tenant_id)
        completed = {r.step_order: r for r in persisted_results if r.status == FlowStepResultStatus.COMPLETED}
        sorted_completed = sorted(completed.values(), key=lambda r: r.step_order)
        segments: list[str] = []
        for r in sorted_completed:
            text = str((r.output_payload_json or {}).get("text", ""))
            segments.append(f"<step_{r.step_order}_output>\n{text}\n</step_{r.step_order}_output>\n")
        state = RunExecutionState(
            completed_by_order=completed,
            prior_results=list(sorted_completed),
            all_previous_segments=segments,
            assistant_cache={},
            json_mode_supported={},
            file_cache={},
            step_names_by_order={
                item.step_order: item.user_description.strip()
                for item in steps
                if isinstance(item.user_description, str) and item.user_description.strip()
            },
        )

        logger.info("flow_executor.steps_parsed run_id=%s step_count=%d", run_id, len(steps))
        for step in sorted(steps, key=lambda item: item.step_order):
            latest_run = await self.flow_run_repo.get(run_id=run_id, tenant_id=tenant_id, flow_id=flow_id)
            if latest_run.status in self._TERMINAL_STATUSES:
                return {"status": "skipped", "reason": f"run_{latest_run.status.value}"}

            if not await self._flow_is_active(flow_id=flow_id, tenant_id=tenant_id):
                reason = "Flow was deleted during execution."
                await self.flow_run_repo.mark_pending_steps_cancelled(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    error_message=reason,
                )
                await self.flow_run_repo.update_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=FlowRunStatus.CANCELLED,
                    error_message=reason,
                    from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                )
                await self._commit()
                return {"status": "cancelled", "reason": "flow_deleted"}

            claimed = await self.flow_run_repo.claim_step_result(
                run_id=run_id,
                step_id=step.step_id,
                tenant_id=tenant_id,
            )
            await self._commit()
            if claimed is None:
                existing = await self.flow_run_repo.get_step_result(
                    run_id=run_id,
                    step_id=step.step_id,
                    tenant_id=tenant_id,
                )
                if existing is None:
                    error = f"Missing step result for step {step.step_id}"
                    await self.flow_run_repo.update_status(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        status=FlowRunStatus.FAILED,
                        error_message=error,
                        from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                    )
                    await self._commit()
                    return {"status": "failed", "error": "step_missing"}
                if existing.status in (
                    FlowStepResultStatus.PENDING,
                    FlowStepResultStatus.RUNNING,
                ):
                    return {"status": "skipped", "reason": "step_already_claimed"}
                # Retry-safe: inject already-completed step into state
                if existing.status == FlowStepResultStatus.COMPLETED:
                    if existing.step_order not in state.completed_by_order:
                        state.append_completed(existing)
                continue

            attempt_no = retry_count + 1
            await self.flow_run_repo.create_or_get_attempt_started(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step.step_id,
                step_order=step.step_order,
                attempt_no=attempt_no,
                celery_task_id=celery_task_id,
            )
            await self._commit()

            logger.info(
                "flow_executor.step_start run_id=%s step_order=%d step_id=%s input_type=%s output_type=%s",
                run_id, step.step_order, step.step_id, step.input_type, step.output_type,
            )
            try:
                output = await self._execute_step(step=step, run=latest_run, state=state)
            except TypedIOValidationException as typed_exc:
                contract_diag = None
                failed_input_payload = getattr(typed_exc, "input_payload_json", None)
                resolved_input_source = step.input_source
                if isinstance(failed_input_payload, dict):
                    contract_diag = failed_input_payload.get("contract_validation")
                    payload_source = failed_input_payload.get("input_source")
                    if isinstance(payload_source, str) and payload_source:
                        resolved_input_source = payload_source
                else:
                    failed_input_payload = {
                        "text": "",
                        "source_text": "",
                        "input_source": step.input_source,
                        "used_question_binding": False,
                        "legacy_prompt_binding_used": False,
                    }
                logger.error(
                    "flow_executor.step_typed_io_error run_id=%s step_order=%d input_type=%s input_source=%s code=%s schema_type_hint=%s parse_attempted=%s parse_succeeded=%s candidate_type=%s error=%s",
                    run_id,
                    step.step_order,
                    step.input_type,
                    resolved_input_source,
                    typed_exc.code,
                    contract_diag.get("schema_type_hint") if isinstance(contract_diag, dict) else None,
                    contract_diag.get("parse_attempted") if isinstance(contract_diag, dict) else None,
                    contract_diag.get("parse_succeeded") if isinstance(contract_diag, dict) else None,
                    contract_diag.get("candidate_type") if isinstance(contract_diag, dict) else None,
                    str(typed_exc),
                )
                await self._rollback()
                await self.flow_run_repo.finish_attempt(
                    run_id=run_id,
                    step_id=step.step_id,
                    attempt_no=attempt_no,
                    tenant_id=tenant_id,
                    status=FlowStepAttemptStatus.FAILED,
                    error_code=typed_exc.code,
                    error_message=str(typed_exc),
                )
                exc = typed_exc  # alias for shared failure path below
                failed_updates: dict[str, Any] = {
                    "status": FlowStepResultStatus.FAILED,
                    "error_message": str(exc),
                }
                if isinstance(failed_input_payload, dict):
                    failed_updates["input_payload_json"] = failed_input_payload
                failed_prompt = getattr(typed_exc, "effective_prompt", None)
                if isinstance(failed_prompt, str):
                    failed_updates["effective_prompt"] = failed_prompt
                failed_result = claimed.model_copy(
                    update=failed_updates,
                    deep=True,
                )
                await self.flow_repo.save_step_result(run_id, failed_result, tenant_id=tenant_id)
                await self.flow_run_repo.update_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=FlowRunStatus.FAILED,
                    error_message=str(exc),
                    from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                )
                await self._commit()
                return {"status": "failed", "error": str(exc)}
            except Exception as exc:
                logger.exception(
                    "flow_executor.step_failed run_id=%s step_order=%d error=%s",
                    run_id, step.step_order, str(exc),
                )
                await self._rollback()
                await self.flow_run_repo.finish_attempt(
                    run_id=run_id,
                    step_id=step.step_id,
                    attempt_no=attempt_no,
                    tenant_id=tenant_id,
                    status=FlowStepAttemptStatus.FAILED,
                    error_code="step_execution_failed",
                    error_message=str(exc),
                )
                failed_result = claimed.model_copy(
                    update={
                        "status": FlowStepResultStatus.FAILED,
                        "error_message": str(exc),
                    },
                    deep=True,
                )
                await self.flow_repo.save_step_result(run_id, failed_result, tenant_id=tenant_id)
                await self.flow_run_repo.update_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=FlowRunStatus.FAILED,
                    error_message=str(exc),
                    from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                )
                await self._commit()
                return {"status": "failed", "error": str(exc)}

            step_result = FlowStepResult(
                id=claimed.id,
                flow_run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step.step_id,
                step_order=step.step_order,
                assistant_id=step.assistant_id,
                input_payload_json={
                    "text": output.input_text,
                    "source_text": output.source_text,
                    "input_source": output.input_source,
                    "used_question_binding": output.used_question_binding,
                    "legacy_prompt_binding_used": output.legacy_prompt_binding_used,
                    **(
                        {"rag": output.rag_metadata}
                        if output.rag_metadata is not None
                        else {}
                    ),
                    **(
                        {"contract_validation": output.contract_validation}
                        if output.contract_validation is not None
                        else {}
                    ),
                    **(
                        {"diagnostics": [
                            {"code": d.code, "message": d.message, "severity": d.severity}
                            for d in output.diagnostics
                        ]}
                        if output.diagnostics
                        else {}
                    ),
                },
                effective_prompt=output.effective_prompt,
                output_payload_json=self._build_output_payload(output),
                model_parameters_json=output.model_parameters_json,
                num_tokens_input=output.num_tokens_input,
                num_tokens_output=output.num_tokens_output,
                status=FlowStepResultStatus.COMPLETED,
                error_message=None,
                flow_step_execution_hash=self._execution_hash(
                    run_id=run_id,
                    step_id=step.step_id,
                    prompt=output.effective_prompt,
                    model_parameters=output.model_parameters_json,
                ),
                tool_calls_metadata=output.tool_calls_metadata,
                created_at=claimed.created_at,
                updated_at=claimed.updated_at,
            )
            await self.flow_repo.save_step_result(run_id, step_result, tenant_id=tenant_id)
            logger.info("flow_executor.step_completed run_id=%s step_order=%d", run_id, step.step_order)
            await self.flow_run_repo.finish_attempt(
                run_id=run_id,
                step_id=step.step_id,
                attempt_no=attempt_no,
                tenant_id=tenant_id,
                status=FlowStepAttemptStatus.COMPLETED,
            )
            await self._commit()

            # Track completed step in run state
            state.append_completed(step_result)

            if step.output_mode == "http_post":
                try:
                    webhook_context = self.variable_resolver.build_context(
                        latest_run.input_payload_json,
                        state.prior_results,
                        current_step_order=step.step_order + 1,
                        step_names_by_order=state.step_names_by_order,
                    )
                    webhook_context["text"] = output.full_text
                    if output.structured_output is not None:
                        webhook_context["structured"] = output.structured_output
                    await self._deliver_webhook(
                        step=step,
                        text_payload=output.full_text,
                        run=latest_run,
                        context=webhook_context,
                    )
                except Exception as exc:
                    failed_delivery_payload = dict(step_result.output_payload_json or {})
                    failed_delivery_payload["webhook_delivered"] = False
                    failed_delivery_payload["webhook_error"] = str(exc)
                    step_result = step_result.model_copy(
                        update={"output_payload_json": failed_delivery_payload},
                        deep=True,
                    )
                    await self.flow_repo.save_step_result(run_id, step_result, tenant_id=tenant_id)
                    await self.flow_run_repo.update_status(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        status=FlowRunStatus.FAILED,
                        error_message=f"Webhook delivery failed: {exc}",
                        from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                    )
                    await self._commit()
                    return {"status": "failed", "error": str(exc)}

                delivered_payload = dict(step_result.output_payload_json or {})
                delivered_payload["webhook_delivered"] = True
                step_result = step_result.model_copy(
                    update={"output_payload_json": delivered_payload},
                    deep=True,
                )
                await self.flow_repo.save_step_result(run_id, step_result, tenant_id=tenant_id)
                await self._commit()

        results = await self.flow_run_repo.list_step_results(run_id=run_id, tenant_id=tenant_id)
        if any(item.status == FlowStepResultStatus.FAILED for item in results):
            await self.flow_run_repo.update_status(
                run_id=run_id,
                tenant_id=tenant_id,
                status=FlowRunStatus.FAILED,
                error_message="One or more flow steps failed.",
                from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
            )
            await self._commit()
            return {"status": "failed"}

        if any(
            item.status in (FlowStepResultStatus.PENDING, FlowStepResultStatus.RUNNING)
            for item in results
        ):
            return {"status": "skipped", "reason": "run_in_progress"}

        if any(item.status == FlowStepResultStatus.CANCELLED for item in results):
            await self.flow_run_repo.update_status(
                run_id=run_id,
                tenant_id=tenant_id,
                status=FlowRunStatus.CANCELLED,
                error_message="One or more steps were cancelled.",
                from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
            )
            await self._commit()
            return {"status": "cancelled"}

        last_completed = next(
            (
                item
                for item in sorted(results, key=lambda result: result.step_order, reverse=True)
                if item.status == FlowStepResultStatus.COMPLETED
            ),
            None,
        )
        await self.flow_run_repo.update_status(
            run_id=run_id,
            tenant_id=tenant_id,
            status=FlowRunStatus.COMPLETED,
            output_payload_json=last_completed.output_payload_json if last_completed else None,
            from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
        )
        await self._commit()
        return {"status": "completed"}

    async def _execute_step(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState | None = None,
    ) -> StepExecutionOutput:
        if state is None:
            state = RunExecutionState(
                completed_by_order={},
                prior_results=[],
                all_previous_segments=[],
                assistant_cache={},
                json_mode_supported={},
                file_cache={},
            )

        logger.info(
            "flow_executor.execute_step run_id=%s step_order=%d input_type=%s output_type=%s",
            run.id, step.step_order, step.input_type, step.output_type,
        )

        # Use state's prior results instead of per-step DB fetch
        context_results = [item for item in state.prior_results if item.status == FlowStepResultStatus.COMPLETED]
        context = self.variable_resolver.build_context(
            run.input_payload_json,
            context_results,
            current_step_order=step.step_order,
            step_names_by_order=state.step_names_by_order,
        )
        assistant = await self._load_assistant(step.assistant_id, state)
        prompt_text = assistant.get_prompt_text()
        logger.debug("flow_executor.resolving_input run_id=%s step_order=%d", run.id, step.step_order)
        effective_prompt = ""
        input_payload_for_result = {
            "text": "",
            "source_text": "",
            "input_source": step.input_source,
            "used_question_binding": False,
            "legacy_prompt_binding_used": False,
        }
        try:
            step_input = await self._resolve_step_input(
                step=step,
                context=context,
                run=run,
                prior_results=state.prior_results,
                assistant_prompt_text=prompt_text,
                state=state,
            )
        except TypedIOValidationException as exc:
            raise self._attach_typed_failure_context(
                exc,
                input_payload_for_result=input_payload_for_result,
                effective_prompt=effective_prompt,
            ) from exc
        input_payload_for_result.update(
            {
                "text": step_input.text,
                "source_text": step_input.source_text,
                "input_source": step_input.input_source,
                "used_question_binding": step_input.used_question_binding,
                "legacy_prompt_binding_used": step_input.legacy_prompt_binding_used,
            }
        )

        logger.info(
            "flow_executor.input_resolved run_id=%s step_order=%d has_files=%s has_structured=%s text_len=%d",
            run.id, step.step_order, step_input.files is not None and len(step_input.files) > 0,
            step_input.structured is not None, len(step_input.text),
        )
        contract_validation: dict[str, Any] | None = None

        # Runtime guards for unsupported types (driven by type_policies)
        policy = INPUT_TYPE_POLICIES.get(step.input_type)
        if policy and not policy.supported:
            raise self._attach_typed_failure_context(
                TypedIOValidationException(
                    f"Input type '{step.input_type}' is not yet supported in runtime execution.",
                    code="typed_io_unsupported_type",
                ),
                input_payload_for_result=input_payload_for_result,
                effective_prompt=effective_prompt,
            )
        if step.input_type == "document" and step.input_source != "flow_input":
            raise self._attach_typed_failure_context(
                TypedIOValidationException(
                    f"Step {step.step_order}: input_type 'document' is not supported with input_source '{step.input_source}'.",
                    code="typed_io_document_source_unsupported",
                ),
                input_payload_for_result=input_payload_for_result,
                effective_prompt=effective_prompt,
            )

        # Strict extraction validation (uses raw, pre-binding text)
        if policy and policy.requires_extraction and not step_input.raw_extracted_text.strip():
            raise self._attach_typed_failure_context(
                TypedIOValidationException(
                    f"Step {step.step_order}: {step.input_type} extraction produced empty text.",
                    code="typed_io_empty_extraction",
                ),
                input_payload_for_result=input_payload_for_result,
                effective_prompt=effective_prompt,
            )

        # Image file validation
        if policy and policy.requires_files:
            usable = [f for f in (step_input.files or []) if (getattr(f, "mimetype", None) or "").startswith("image/")]
            if not usable:
                raise self._attach_typed_failure_context(
                    TypedIOValidationException(
                        f"Step {step.step_order}: image input requires at least one valid image file.",
                        code="typed_io_missing_required_files",
                    ),
                    input_payload_for_result=input_payload_for_result,
                    effective_prompt=effective_prompt,
                )
            non_images = [
                getattr(f, "name", "unknown")
                for f in (step_input.files or [])
                if not (getattr(f, "mimetype", None) or "").startswith("image/")
            ]
            if non_images:
                raise self._attach_typed_failure_context(
                    TypedIOValidationException(
                        f"Step {step.step_order}: non-image file(s) for image input: {non_images}",
                        code="typed_io_invalid_file_type",
                    ),
                    input_payload_for_result=input_payload_for_result,
                    effective_prompt=effective_prompt,
                )

        effective_prompt = (
            self.variable_resolver.interpolate(prompt_text, context) if prompt_text else ""
        )

        # Input contract validation
        if step.input_contract:
            from intric.flows.output_processing import validate_against_contract
            if step.input_type == "json" and step_input.structured is not None:
                contract_validation = {
                    "schema_type_hint": self._schema_type_hint(step.input_contract),
                    "parse_attempted": False,
                    "parse_succeeded": True,
                    "candidate_type": type(step_input.structured).__name__,
                }
                try:
                    validate_against_contract(
                        step_input.structured, step.input_contract, label=f"Step {step.step_order} input"
                    )
                except TypedIOValidationException as exc:
                    input_payload_for_result["contract_validation"] = contract_validation
                    raise self._attach_typed_failure_context(
                        exc,
                        input_payload_for_result=input_payload_for_result,
                        effective_prompt=effective_prompt,
                    ) from exc
            elif step.input_type == "json":
                contract_validation = {
                    "schema_type_hint": self._schema_type_hint(step.input_contract),
                    "parse_attempted": False,
                    "parse_succeeded": False,
                    "candidate_type": "str",
                }
                input_payload_for_result["contract_validation"] = contract_validation
                typed_error = TypedIOValidationException(
                    f"Step {step.step_order}: input_type 'json' requires valid JSON input before contract validation.",
                    code="typed_io_invalid_json_input",
                )
                raise self._attach_typed_failure_context(
                    typed_error,
                    input_payload_for_result=input_payload_for_result,
                    effective_prompt=effective_prompt,
                ) from typed_error
            elif step.input_type == "text":
                candidate, contract_validation = self._prepare_text_contract_candidate(
                    text=step_input.text,
                    schema=step.input_contract,
                )
                try:
                    validate_against_contract(
                        candidate, step.input_contract, label=f"Step {step.step_order} input"
                    )
                except TypedIOValidationException as exc:
                    input_payload_for_result["contract_validation"] = contract_validation
                    raise self._attach_typed_failure_context(
                        exc,
                        input_payload_for_result=input_payload_for_result,
                        effective_prompt=effective_prompt,
                    ) from exc

        if contract_validation is not None:
            input_payload_for_result["contract_validation"] = contract_validation
            logger.info(
                "flow_executor.contract_validation run_id=%s step_order=%d input_type=%s input_source=%s schema_type_hint=%s parse_attempted=%s parse_succeeded=%s candidate_type=%s",
                run.id,
                step.step_order,
                step.input_type,
                step_input.input_source,
                contract_validation["schema_type_hint"],
                contract_validation["parse_attempted"],
                contract_validation["parse_succeeded"],
                contract_validation["candidate_type"],
            )
        await self._commit()

        diagnostics = list(step_input.diagnostics)
        info_blob_chunks, rag_metadata, rag_diagnostics = await self._retrieve_rag_chunks(
            assistant=assistant,
            question=step_input.text,
            run_id=run.id,
            step_order=step.step_order,
        )
        diagnostics.extend(rag_diagnostics)

        # Channel dispatch — files_only types send files, not text to LLM
        llm_files: list[Any] = []
        if policy and policy.channel == "files_only":
            llm_files = step_input.files or []
        else:
            llm_files = step_input.files or []

        # Prepare model kwargs — inject JSON mode when applicable
        model_kwargs = assistant.completion_model_kwargs
        original_kwargs = model_kwargs
        cache_key = self._json_mode_cache_key(assistant)
        if step.output_type == "json" and state.json_mode_supported.get(cache_key, True):
            try:
                model_kwargs = assistant.completion_model_kwargs.model_copy(
                    update={"response_format": {"type": "json_object"}}
                )
            except Exception:
                state.json_mode_supported[cache_key] = False

        logger.info("flow_executor.llm_call run_id=%s step_order=%d", run.id, step.step_order)
        try:
            response = await assistant.get_response(
                question=step_input.text,
                completion_service=self.completion_service,
                model_kwargs=model_kwargs,
                files=llm_files,
                info_blob_chunks=info_blob_chunks,
                stream=False,
                prompt_override=effective_prompt,
            )
        except Exception as model_exc:
            if step.output_type == "json" and self._is_json_mode_rejection(model_exc):
                state.json_mode_supported[cache_key] = False
                response = await assistant.get_response(
                    question=step_input.text,
                    completion_service=self.completion_service,
                    model_kwargs=original_kwargs,
                    files=llm_files,
                    info_blob_chunks=info_blob_chunks,
                    stream=False,
                    prompt_override=effective_prompt,
                )
            else:
                raise

        logger.info(
            "flow_executor.llm_done run_id=%s step_order=%d tokens=%s",
            run.id, step.step_order, response.total_token_count,
        )
        completion = response.completion
        if isinstance(completion, str):
            full_text = completion
            tool_calls = None
            reasoning_tokens = 0
        else:
            completion = completion if isinstance(completion, Completion) else Completion(text=str(completion))
            full_text = completion.text or ""
            tool_calls = (
                [tc.__dict__ for tc in completion.tool_calls_metadata]
                if completion.tool_calls_metadata
                else None
            )
            reasoning_tokens = completion.reasoning_token_count or 0

        # Typed output processing (always active)
        structured_output = None
        artifacts = None
        logger.info(
            "flow_executor.typed_output_processing run_id=%s step_order=%d output_type=%s",
            run.id, step.step_order, step.output_type,
        )
        try:
            structured_output, artifacts = await self._process_typed_output(
                full_text=full_text, step=step, run=run
            )
        except TypedIOValidationException as exc:
            raise self._attach_typed_failure_context(
                exc,
                input_payload_for_result=input_payload_for_result,
                effective_prompt=effective_prompt,
            ) from exc
        logger.info(
            "flow_executor.typed_output_done run_id=%s step_order=%d has_structured=%s has_artifacts=%s",
            run.id, step.step_order, structured_output is not None,
            artifacts is not None and len(artifacts) > 0,
        )

        persisted_text, generated_file_ids = await self._apply_output_cap(
            text=full_text,
            run=run,
            step=step,
        )
        return StepExecutionOutput(
            input_text=step_input.text,
            source_text=step_input.source_text,
            input_source=step_input.input_source,
            used_question_binding=step_input.used_question_binding,
            legacy_prompt_binding_used=step_input.legacy_prompt_binding_used,
            full_text=full_text,
            persisted_text=persisted_text,
            generated_file_ids=generated_file_ids,
            tool_calls_metadata=tool_calls,
            num_tokens_input=response.total_token_count,
            num_tokens_output=count_tokens(full_text) + reasoning_tokens,
            effective_prompt=effective_prompt,
            model_parameters_json=self._effective_model_parameters(assistant),
            contract_validation=contract_validation,
            structured_output=structured_output,
            artifacts=artifacts,
            diagnostics=diagnostics,
            rag_metadata=rag_metadata,
        )

    async def _retrieve_rag_chunks(
        self,
        *,
        assistant: Any,
        question: str,
        run_id: UUID,
        step_order: int,
    ) -> tuple[list[Any], dict[str, Any], list[StepDiagnostic]]:
        info_blob_chunks: list[Any] = []
        rag_diagnostics: list[StepDiagnostic] = []
        rag_metadata: dict[str, Any] = {
            "attempted": False,
            "status": "skipped_no_service",
            "version": 1,
            "timeout_seconds": self.rag_retrieval_timeout_seconds,
            "include_info_blobs": False,
            "chunks_retrieved": 0,
            "unique_sources": 0,
            "source_ids": [],
            "source_ids_short": [],
            "error_code": None,
        }
        if self.references_service is None:
            rag_metadata["status"] = "skipped_no_service"
            return info_blob_chunks, rag_metadata, rag_diagnostics
        if not assistant.has_knowledge():
            rag_metadata["status"] = "skipped_no_knowledge"
            return info_blob_chunks, rag_metadata, rag_diagnostics
        if not question.strip():
            rag_metadata["status"] = "skipped_no_input"
            return info_blob_chunks, rag_metadata, rag_diagnostics

        rag_metadata["attempted"] = True
        try:
            # Flow runtime intentionally uses v1 retrieval (autocut + bounded chunks)
            datastore_result = await asyncio.wait_for(
                self.references_service.get_references(
                    question=question,
                    collections=assistant.collections,
                    websites=assistant.websites,
                    integration_knowledge_list=assistant.integration_knowledge_list,
                    version=1,
                    include_info_blobs=False,
                ),
                timeout=self.rag_retrieval_timeout_seconds,
            )
            info_blob_chunks = datastore_result.chunks
            source_ids = list(
                dict.fromkeys(
                    str(getattr(chunk, "info_blob_id", ""))
                    for chunk in info_blob_chunks
                    if getattr(chunk, "info_blob_id", None) is not None
                )
            )
            rag_metadata["status"] = "success"
            rag_metadata["chunks_retrieved"] = len(info_blob_chunks)
            rag_metadata["unique_sources"] = len(source_ids)
            rag_metadata["source_ids"] = source_ids
            rag_metadata["source_ids_short"] = [source_id[:8] for source_id in source_ids]
        except asyncio.TimeoutError:
            rag_metadata["status"] = "timeout"
            rag_metadata["error_code"] = "rag_retrieval_timeout"
            rag_diagnostics.append(
                StepDiagnostic(
                    code="rag_retrieval_timeout",
                    message=f"RAG retrieval exceeded {self.rag_retrieval_timeout_seconds}s timeout.",
                )
            )
            logger.warning(
                "flow_executor.rag_timeout run_id=%s step_order=%d timeout=%s",
                run_id,
                step_order,
                self.rag_retrieval_timeout_seconds,
            )
        except Exception:
            rag_metadata["status"] = "error"
            rag_metadata["error_code"] = "rag_retrieval_failed"
            rag_diagnostics.append(
                StepDiagnostic(
                    code="rag_retrieval_failed",
                    message="RAG retrieval failed; continuing without knowledge chunks.",
                )
            )
            logger.warning(
                "flow_executor.rag_failed run_id=%s step_order=%d",
                run_id,
                step_order,
                exc_info=True,
            )
        return info_blob_chunks, rag_metadata, rag_diagnostics

    async def _flow_is_active(self, *, flow_id: UUID, tenant_id: UUID) -> bool:
        flow_id_in_db = await self.flow_repo.session.scalar(
            sa.select(Flows.id)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
        )
        return flow_id_in_db is not None

    async def _resolve_step_input(
        self,
        *,
        step: RuntimeStep,
        context: dict[str, Any],
        run: FlowRun,
        prior_results: list[FlowStepResult],
        assistant_prompt_text: str | None = None,
        state: RunExecutionState | None = None,
    ) -> StepInputValue:
        if step.step_order == 1 and step.input_source in {"previous_step", "all_previous_steps"}:
            raise TypedIOValidationException(
                "Step 1 cannot use previous_step/all_previous_steps input source. Use flow_input.",
                code="typed_io_invalid_input_source_position",
            )
        if step.input_type == "json" and step.input_source == "all_previous_steps":
            raise TypedIOValidationException(
                f"Step {step.step_order}: input_type 'json' is incompatible with input_source "
                f"'all_previous_steps' (concatenated text is not valid JSON).",
                code="typed_io_invalid_input_source_combination",
            )
        structured: dict[str, Any] | list[Any] | None = None
        if step.input_source in ("http_get", "http_post"):
            source_text, structured = await self._resolve_http_input_source_text(
                step=step,
                run=run,
                context=context,
            )
        else:
            source_text = self._resolve_input_source_text(
                input_source=step.input_source,
                run=run,
                step_order=step.step_order,
                prior_results=prior_results,
                state=state,
            )
        input_text = source_text
        raw_extracted_text = ""
        used_question_binding = False
        legacy_prompt_binding_used = False

        bindings = step.input_bindings if isinstance(step.input_bindings, dict) else None
        if bindings is not None:
            question_template = bindings.get("question")
            if isinstance(question_template, str):
                interpolated_question = self.variable_resolver.interpolate(question_template, context)
                if self._is_legacy_mirrored_question_binding(
                    question_template=question_template,
                    interpolated_question=interpolated_question,
                    assistant_prompt_text=assistant_prompt_text,
                ):
                    legacy_prompt_binding_used = True
                else:
                    input_text = interpolated_question
                    used_question_binding = True

            legacy_text_template = bindings.get("text")
            if isinstance(legacy_text_template, str):
                legacy_prompt_binding_used = True

        # Resolve files from flow input for document/image/file types
        files = None
        if step.input_source == "flow_input" and step.input_type in ("document", "image", "file"):
            raw_file_ids = (run.input_payload_json or {}).get("file_ids", [])
            logger.info(
                "flow_executor.file_resolve run_id=%s step_order=%d input_type=%s file_ids=%s",
                run.id, step.step_order, step.input_type, raw_file_ids,
            )
            if raw_file_ids is not None and not isinstance(raw_file_ids, list):
                raise TypedIOValidationException(
                    "file_ids must be a list.",
                    code="typed_io_invalid_file_ids",
                )
            if raw_file_ids:
                try:
                    requested_ids = [UUID(str(fid)) for fid in raw_file_ids]
                except (TypeError, ValueError, AttributeError) as exc:
                    raise TypedIOValidationException(
                        f"Invalid file_ids payload: {raw_file_ids}",
                        code="typed_io_invalid_file_ids",
                    ) from exc
                cache_key = frozenset(requested_ids)
                if state and cache_key in state.file_cache:
                    files = state.file_cache[cache_key]
                else:
                    files = await self.file_repo.get_list_by_id_and_user(
                        requested_ids, user_id=self.user.id
                    )
                    if state:
                        state.file_cache[cache_key] = files
                returned_ids = {f.id for f in files}
                missing = [fid for fid in requested_ids if fid not in returned_ids]
                logger.info(
                    "flow_executor.file_resolve_result run_id=%s step_order=%d requested=%d returned=%d missing=%s",
                    run.id, step.step_order, len(requested_ids), len(files), missing,
                )
                if missing:
                    raise TypedIOValidationException(
                        f"File(s) not found or not accessible: {missing}",
                        code="typed_io_file_not_found",
                    )
                if step.input_type in ("document", "file") and files:
                    extracted = [
                        str(f.text).strip()
                        for f in files
                        if isinstance(getattr(f, "text", None), str) and str(f.text).strip()
                    ]
                    logger.info(
                        "flow_executor.document_text_extracted run_id=%s step_order=%d file_count=%d extracted_count=%d",
                        run.id, step.step_order, len(files), len(extracted),
                    )
                    if extracted:
                        input_text = "\n\n".join(extracted)
                        raw_extracted_text = input_text

        # For json input, prefer structured data from source-specific parsing or previous step
        if step.input_type == "json":
            if structured is not None:
                input_text = json.dumps(structured, ensure_ascii=False)
            elif step.input_source == "previous_step":
                prev = next(
                    (r for r in prior_results if r.step_order == step.step_order - 1),
                    None,
                )
                if prev and isinstance(prev.output_payload_json, dict):
                    prev_structured = prev.output_payload_json.get("structured")
                    if prev_structured is not None:
                        structured = prev_structured
                        input_text = json.dumps(prev_structured, ensure_ascii=False)
            if structured is None:
                try:
                    structured = json.loads(input_text)
                except (json.JSONDecodeError, ValueError):
                    pass

        self._enforce_inline_input_cap(
            text=input_text,
            step_order=step.step_order,
            input_source=step.input_source,
        )

        # Flag empty input from previous_step/all_previous_steps for debug visibility
        diagnostics: list[StepDiagnostic] = []
        if step.input_source in ("previous_step", "all_previous_steps"):
            has_substantive_input = False
            if step.input_source == "previous_step":
                has_substantive_input = bool(source_text.strip())
            else:
                # all_previous_steps wraps content in XML tags even when inner text is empty;
                # check actual prior result text instead of the assembled source_text
                for pr in prior_results:
                    if pr.step_order < step.step_order and isinstance(pr.output_payload_json, dict):
                        if str(pr.output_payload_json.get("text", "")).strip():
                            has_substantive_input = True
                            break
            if not has_substantive_input:
                diagnostics.append(StepDiagnostic(
                    code="empty_prior_step_input",
                    message=(
                        f"Step {step.step_order}: input_source '{step.input_source}' resolved to "
                        f"empty text. The LLM received no substantive input from prior steps."
                    ),
                ))

        return StepInputValue(
            text=input_text,
            source_text=source_text,
            files=files,
            structured=structured,
            raw_extracted_text=raw_extracted_text,
            input_source=step.input_source,
            used_question_binding=used_question_binding,
            legacy_prompt_binding_used=legacy_prompt_binding_used,
            diagnostics=diagnostics,
        )

    def _enforce_inline_input_cap(
        self,
        *,
        text: str,
        step_order: int,
        input_source: str,
    ) -> None:
        if len(text.encode("utf-8")) <= self.max_inline_text_bytes:
            return
        raise TypedIOValidationException(
            f"Step {step_order}: resolved input for '{input_source}' exceeded max inline text bytes.",
            code="typed_io_input_too_large",
        )

    @staticmethod
    def _normalize_binding_text(value: str) -> str:
        return " ".join(value.split())

    def _is_legacy_mirrored_question_binding(
        self,
        *,
        question_template: str,
        interpolated_question: str,
        assistant_prompt_text: str | None,
    ) -> bool:
        if not isinstance(assistant_prompt_text, str) or assistant_prompt_text.strip() == "":
            return False
        prompt_normalized = self._normalize_binding_text(assistant_prompt_text)
        return (
            self._normalize_binding_text(question_template) == prompt_normalized
            or self._normalize_binding_text(interpolated_question) == prompt_normalized
        )

    def _resolve_input_source_text(
        self,
        *,
        input_source: str,
        run: FlowRun,
        step_order: int,
        prior_results: list[FlowStepResult],
        state: RunExecutionState | None = None,
    ) -> str:
        if input_source == "flow_input":
            payload = run.input_payload_json or {}
            if isinstance(payload.get("text"), str):
                return payload["text"]
            return json.dumps(payload, ensure_ascii=False)
        if input_source == "previous_step":
            previous = next((item for item in prior_results if item.step_order == step_order - 1), None)
            if previous and isinstance(previous.output_payload_json, dict):
                text = str(previous.output_payload_json.get("text", ""))
                if not text.strip():
                    logger.warning(
                        "flow_executor.empty_previous_step_input run_id=%s step_order=%d "
                        "previous_step_order=%d reason=previous_output_text_empty",
                        run.id, step_order, step_order - 1,
                    )
                return text
            logger.warning(
                "flow_executor.empty_previous_step_input run_id=%s step_order=%d "
                "previous_step_order=%d reason=%s",
                run.id, step_order, step_order - 1,
                "no_previous_result" if previous is None else "output_not_dict",
            )
            return ""
        if input_source == "all_previous_steps":
            # Use pre-built accumulated text from state when available
            if state:
                return state.all_previous_text
            parts = []
            for previous in sorted(prior_results, key=lambda item: item.step_order):
                if previous.step_order >= step_order:
                    continue
                text = ""
                if isinstance(previous.output_payload_json, dict):
                    text = str(previous.output_payload_json.get("text", ""))
                parts.append(f"<step_{previous.step_order}_output>\n{text}\n</step_{previous.step_order}_output>")
            return "\n".join(parts)
        if input_source in ("http_get", "http_post"):
            raise BadRequestException(
                f"Input source '{input_source}' is not yet supported in runtime execution."
            )
        raise BadRequestException(f"Unsupported input source '{input_source}'.")

    async def _resolve_http_input_source_text(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        context: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | list[Any] | None]:
        if not isinstance(step.input_config, dict):
            raise TypedIOValidationException(
                f"Step {step.step_order}: HTTP input source requires input_config object.",
                code="typed_io_http_invalid_config",
            )
        resolved_config = decrypt_step_headers_for_runtime(
            config=step.input_config,
            encryption_service=self.encryption_service,
        ) or {}
        if not isinstance(resolved_config, dict):
            raise TypedIOValidationException(
                f"Step {step.step_order}: HTTP input config must be an object.",
                code="typed_io_http_invalid_config",
            )

        url_raw = resolved_config.get("url")
        if not isinstance(url_raw, str) or not url_raw.strip():
            raise TypedIOValidationException(
                f"Step {step.step_order}: input_config.url is required for HTTP input.",
                code="typed_io_http_invalid_config",
            )
        url = self.variable_resolver.interpolate(url_raw, context).strip()
        timeout_seconds = self._resolve_http_timeout_seconds(
            resolved_config.get("timeout_seconds"),
            step_order=step.step_order,
            config_label="input_config",
        )
        headers = self._build_http_headers(
            resolved_config.get("headers"),
            context=context,
            step_order=step.step_order,
            config_label="input_config",
        )

        method = "GET" if step.input_source == "http_get" else "POST"
        body_bytes, json_body = self._resolve_http_request_body(
            method=method,
            config=resolved_config,
            context=context,
            step_order=step.step_order,
            config_label="input_config",
        )

        start_time = time.monotonic()
        try:
            response = await self._send_http_request(
                method=method,
                url=url,
                headers=headers,
                timeout_seconds=timeout_seconds,
                body_bytes=body_bytes,
                json_body=json_body,
            )
        except TypedIOValidationException as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            await self._audit_http_outbound(
                run=run, step=step, url=url, method=method,
                call_type="http_input", outcome=Outcome.FAILURE,
                error_message=str(exc), duration_ms=duration_ms,
            )
            raise
        except httpx.TimeoutException as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            err_msg = f"Step {step.step_order}: HTTP {method} input timed out after {timeout_seconds:g}s."
            await self._audit_http_outbound(
                run=run, step=step, url=url, method=method,
                call_type="http_input", outcome=Outcome.FAILURE,
                error_message=err_msg, duration_ms=duration_ms,
            )
            raise TypedIOValidationException(
                err_msg,
                code="typed_io_http_timeout",
            ) from exc
        except httpx.HTTPError as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            err_msg = f"Step {step.step_order}: HTTP {method} input request failed: {exc}"
            await self._audit_http_outbound(
                run=run, step=step, url=url, method=method,
                call_type="http_input", outcome=Outcome.FAILURE,
                error_message=err_msg, duration_ms=duration_ms,
            )
            raise TypedIOValidationException(
                err_msg,
                code="typed_io_http_connection_error",
            ) from exc

        duration_ms = (time.monotonic() - start_time) * 1000
        if response.status_code >= 400:
            err_msg = f"Step {step.step_order}: HTTP {method} input returned status {response.status_code}."
            await self._audit_http_outbound(
                run=run, step=step, url=url, method=method,
                call_type="http_input", outcome=Outcome.FAILURE,
                error_message=err_msg, status_code=response.status_code,
                duration_ms=duration_ms,
            )
            raise TypedIOValidationException(
                err_msg,
                code="typed_io_http_non_success",
            )

        response_text = self._read_http_response_text(
            response=response,
            step_order=step.step_order,
            code="typed_io_http_response_too_large",
        )

        expects_json = (
            step.input_type == "json"
            or str(resolved_config.get("response_format", "text")) == "json"
        )
        if expects_json:
            try:
                parsed = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                err_msg = f"Step {step.step_order}: HTTP {method} input returned malformed JSON response."
                await self._audit_http_outbound(
                    run=run, step=step, url=url, method=method,
                    call_type="http_input", outcome=Outcome.FAILURE,
                    error_message=err_msg, status_code=response.status_code,
                    duration_ms=duration_ms,
                )
                raise TypedIOValidationException(
                    err_msg,
                    code="typed_io_http_malformed_response",
                ) from exc
            await self._audit_http_outbound(
                run=run, step=step, url=url, method=method,
                call_type="http_input", outcome=Outcome.SUCCESS,
                status_code=response.status_code, duration_ms=duration_ms,
            )
            return json.dumps(parsed, ensure_ascii=False), parsed
        await self._audit_http_outbound(
            run=run, step=step, url=url, method=method,
            call_type="http_input", outcome=Outcome.SUCCESS,
            status_code=response.status_code, duration_ms=duration_ms,
        )
        return response_text, None

    def _resolve_http_timeout_seconds(
        self,
        timeout_value: Any,
        *,
        step_order: int,
        config_label: str,
    ) -> float:
        if timeout_value is None:
            return self.http_request_timeout_seconds
        if not isinstance(timeout_value, (int, float)):
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds must be a number.",
                code="typed_io_http_invalid_config",
            )
        timeout_seconds = float(timeout_value)
        if timeout_seconds <= 0:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds must be greater than zero.",
                code="typed_io_http_invalid_config",
            )
        if timeout_seconds > self.http_max_timeout_seconds:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds cannot exceed {self.http_max_timeout_seconds:g}.",
                code="typed_io_http_invalid_config",
            )
        return timeout_seconds

    def _build_http_headers(
        self,
        headers_raw: Any,
        *,
        context: dict[str, Any],
        step_order: int,
        config_label: str,
    ) -> dict[str, str]:
        if headers_raw is None:
            return {}
        if not isinstance(headers_raw, dict):
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.headers must be an object.",
                code="typed_io_http_invalid_config",
            )
        headers: dict[str, str] = {}
        for key, value in headers_raw.items():
            if not isinstance(key, str):
                raise TypedIOValidationException(
                    f"Step {step_order}: {config_label}.headers keys must be strings.",
                    code="typed_io_http_invalid_config",
                )
            rendered = self._interpolate_http_value(value, context=context)
            headers[key] = str(rendered)
        return headers

    def _resolve_http_request_body(
        self,
        *,
        method: str,
        config: dict[str, Any],
        context: dict[str, Any],
        step_order: int,
        config_label: str,
    ) -> tuple[bytes | None, dict[str, Any] | list[Any] | None]:
        if method != "POST":
            return None, None
        body_template = config.get("body_template")
        body_json = config.get("body_json")
        if body_template is not None and not isinstance(body_template, str):
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.body_template must be a string.",
                code="typed_io_http_invalid_config",
            )
        if body_json is not None and not isinstance(body_json, (dict, list)):
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.body_json must be an object or array.",
                code="typed_io_http_invalid_config",
            )
        if body_template is not None and body_json is not None:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label} cannot define both body_template and body_json.",
                code="typed_io_http_invalid_config",
            )
        if body_json is not None:
            interpolated_json = self._interpolate_http_value(body_json, context=context)
            if not isinstance(interpolated_json, (dict, list)):
                raise TypedIOValidationException(
                    f"Step {step_order}: {config_label}.body_json interpolation must produce object or array.",
                    code="typed_io_http_invalid_config",
                )
            return None, interpolated_json
        if body_template is not None:
            rendered = self.variable_resolver.interpolate(body_template, context)
            return rendered.encode("utf-8"), None
        return None, None

    def _interpolate_http_value(self, value: Any, *, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            if _TEMPLATE_ONLY_PATTERN.match(value):
                rendered = self.variable_resolver.interpolate(value, context)
                try:
                    return json.loads(rendered)
                except (ValueError, json.JSONDecodeError):
                    return rendered
            return self.variable_resolver.interpolate(value, context)
        if isinstance(value, list):
            return [self._interpolate_http_value(item, context=context) for item in value]
        if isinstance(value, dict):
            return {
                str(item_key): self._interpolate_http_value(item_value, context=context)
                for item_key, item_value in value.items()
            }
        return value

    @staticmethod
    def _read_http_response_text(
        *,
        response: httpx.Response,
        step_order: int,
        code: str,
    ) -> str:
        response_bytes = response.content
        if len(response_bytes) > get_settings().flow_max_inline_text_bytes:
            raise TypedIOValidationException(
                f"Step {step_order}: HTTP response exceeded max inline text bytes.",
                code=code,
            )
        return response.text

    async def _send_http_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        body_bytes: bytes | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        read_response_body: bool = True,
    ) -> httpx.Response:
        preflight_resolved_ips = await self._assert_http_url_allowed(url)
        timeout = httpx.Timeout(timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            request = client.build_request(
                method,
                url,
                headers=headers,
                content=body_bytes,
                json=json_body,
            )
            response = await client.send(request, stream=True)
            try:
                self._assert_http_connected_peer_allowed(
                    response=response,
                    preflight_resolved_ips=preflight_resolved_ips,
                )
            except Exception:
                await response.aclose()
                raise
            if not read_response_body:
                detached = httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    request=request,
                )
                await response.aclose()
                return detached

            max_bytes = get_settings().flow_max_inline_text_bytes
            response_bytes = bytearray()
            async for chunk in response.aiter_bytes():
                response_bytes.extend(chunk)
                if len(response_bytes) > max_bytes:
                    await response.aclose()
                    raise TypedIOValidationException(
                        "HTTP response exceeded max inline text bytes.",
                        code="typed_io_http_response_too_large",
                    )

            detached = httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=bytes(response_bytes),
                request=request,
            )
            await response.aclose()
            return detached

    async def _assert_http_url_allowed(self, url: str) -> set[IPAddress] | None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise TypedIOValidationException(
                f"Unsupported HTTP URL scheme: '{parsed.scheme}'.",
                code="typed_io_http_invalid_url",
            )
        host = parsed.hostname
        if not host:
            raise TypedIOValidationException(
                "HTTP URL must include a hostname.",
                code="typed_io_http_invalid_url",
            )
        host_lower = host.strip().lower()
        if host_lower in {"localhost", "localhost.localdomain"}:
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code="typed_io_http_ssrf_blocked",
            )
        if self.http_allow_private_networks:
            return None

        resolved_ips: list[IPAddress]
        try:
            resolved_ips = self._resolve_ip_literal(host_lower)
        except ValueError:
            resolved_ips = await self._resolve_host_ips(
                host=host_lower,
                port=parsed.port or (443 if parsed.scheme == "https" else 80),
            )

        if any(self._is_private_or_local_ip(item) for item in resolved_ips):
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code="typed_io_http_ssrf_blocked",
            )
        return set(resolved_ips)

    def _assert_http_connected_peer_allowed(
        self,
        *,
        response: httpx.Response,
        preflight_resolved_ips: set[IPAddress] | None,
    ) -> None:
        if self.http_allow_private_networks:
            return

        network_stream = response.extensions.get("network_stream")
        if network_stream is None:
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code="typed_io_http_connection_error",
            )

        server_addr = network_stream.get_extra_info("server_addr")
        if not isinstance(server_addr, tuple) or not server_addr:
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code="typed_io_http_connection_error",
            )

        peer_value = server_addr[0]
        if not isinstance(peer_value, str):
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code="typed_io_http_connection_error",
            )

        try:
            peer_ip = ipaddress.ip_address(peer_value)
        except ValueError as exc:
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code="typed_io_http_connection_error",
            ) from exc

        if self._is_private_or_local_ip(peer_ip):
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code="typed_io_http_ssrf_blocked",
            )

        if preflight_resolved_ips and peer_ip not in preflight_resolved_ips:
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code="typed_io_http_ssrf_blocked",
            )

    @staticmethod
    def _resolve_ip_literal(host: str) -> list[IPAddress]:
        return [ipaddress.ip_address(host)]

    async def _resolve_host_ips(self, *, host: str, port: int) -> list[IPAddress]:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise TypedIOValidationException(
                f"Unable to resolve HTTP host '{host}'.",
                code="typed_io_http_connection_error",
            ) from exc
        resolved: list[IPAddress] = []
        for _, _, _, _, sockaddr in infos:
            try:
                resolved.append(ipaddress.ip_address(sockaddr[0]))
            except ValueError:
                continue
        if not resolved:
            raise TypedIOValidationException(
                f"Unable to resolve HTTP host '{host}'.",
                code="typed_io_http_connection_error",
            )
        return resolved

    @staticmethod
    def _is_private_or_local_ip(value: IPAddress) -> bool:
        return (
            value.is_loopback
            or value.is_private
            or value.is_link_local
            or value.is_multicast
            or value.is_reserved
            or value.is_unspecified
        )

    async def _load_assistant(self, assistant_id: UUID, state: RunExecutionState | None = None) -> Any:
        if state and assistant_id in state.assistant_cache:
            return state.assistant_cache[assistant_id]
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        if state:
            state.assistant_cache[assistant_id] = assistant
        return assistant

    @staticmethod
    def _json_mode_cache_key(assistant: Any) -> str:
        cm = assistant.completion_model
        provider = getattr(cm, "provider_type", "unknown") or "unknown"
        name = cm.name if cm else "unknown"
        mid = str(cm.id) if cm and cm.id else "none"
        return f"{provider}:{name}:{mid}"

    @staticmethod
    def _schema_type_hint(schema: dict[str, Any]) -> str:
        raw_type = schema.get("type")
        if isinstance(raw_type, str):
            return raw_type
        if isinstance(raw_type, list):
            type_entries = sorted(str(item) for item in raw_type if isinstance(item, str))
            if type_entries:
                return "|".join(type_entries)
        if isinstance(schema.get("properties"), dict):
            return "object"
        if "items" in schema:
            return "array"
        return "unknown"

    @staticmethod
    def _schema_expects_structured(schema: dict[str, Any]) -> bool:
        raw_type = schema.get("type")
        if isinstance(raw_type, str):
            return raw_type in {"object", "array"}
        if isinstance(raw_type, list):
            return any(item in {"object", "array"} for item in raw_type if isinstance(item, str))
        return isinstance(schema.get("properties"), dict) or "items" in schema

    def _prepare_text_contract_candidate(
        self,
        *,
        text: str,
        schema: dict[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        parse_attempted = self._schema_expects_structured(schema)
        parse_succeeded = False
        candidate: Any = text
        if parse_attempted:
            try:
                candidate = json.loads(text)
                parse_succeeded = True
            except (json.JSONDecodeError, ValueError):
                candidate = text
        return candidate, {
            "schema_type_hint": self._schema_type_hint(schema),
            "parse_attempted": parse_attempted,
            "parse_succeeded": parse_succeeded,
            "candidate_type": type(candidate).__name__,
        }

    @staticmethod
    def _attach_typed_failure_context(
        exc: TypedIOValidationException,
        *,
        input_payload_for_result: dict[str, Any],
        effective_prompt: str,
    ) -> TypedIOValidationException:
        existing_payload = getattr(exc, "input_payload_json", None)
        if not isinstance(existing_payload, dict):
            payload = dict(input_payload_for_result)
            payload.setdefault("text", "")
            payload.setdefault("source_text", payload.get("text", ""))
            payload.setdefault("input_source", "")
            payload.setdefault("used_question_binding", False)
            payload.setdefault("legacy_prompt_binding_used", False)
            setattr(exc, "input_payload_json", payload)
        existing_prompt = getattr(exc, "effective_prompt", None)
        if not isinstance(existing_prompt, str):
            setattr(exc, "effective_prompt", effective_prompt)
        return exc

    @staticmethod
    def _is_json_mode_rejection(exc: Exception) -> bool:
        """Check if LLM error is due to unsupported response_format."""
        msg = str(exc).lower()
        return any(term in msg for term in ("response_format", "json_object", "json mode"))

    async def _audit_http_outbound(
        self,
        *,
        run: FlowRun,
        step: RuntimeStep,
        url: str,
        method: str,
        call_type: str,
        outcome: Outcome,
        error_message: str | None = None,
        status_code: int | None = None,
        duration_ms: float | None = None,
    ) -> None:
        if self.audit_service is None:
            return
        try:
            parts = urlsplit(url)
            safe_url_host = f"{parts.scheme}://{parts.hostname}" if parts.hostname else ""
            safe_url_path = parts.path or "/"
            extra: dict[str, Any] = {
                "call_type": call_type,
                "http_method": method,
                "url_host": safe_url_host,
                "url_path": safe_url_path,
                "flow_id": str(run.flow_id),
                "step_order": step.step_order,
                "step_id": str(step.step_id),
            }
            if step.user_description:
                extra["step_description"] = step.user_description
            if status_code is not None:
                extra["status_code"] = status_code
            if duration_ms is not None:
                extra["duration_ms"] = round(duration_ms, 2)
            await self.audit_service.log_async(
                tenant_id=run.tenant_id,
                actor_id=self.user.id,
                action=ActionType.FLOW_HTTP_OUTBOUND_CALL,
                entity_type=EntityType.FLOW_RUN,
                entity_id=run.id,
                description=f"Flow HTTP {call_type} {method} to {safe_url_host}{safe_url_path}",
                metadata=AuditMetadata.standard(actor=self.user, target=run, extra=extra),
                outcome=outcome,
                error_message=error_message,
            )
        except Exception:
            logger.warning(
                "flow_executor.audit_http_outbound_failed run_id=%s step_order=%d",
                run.id, step.step_order, exc_info=True,
            )

    async def _deliver_webhook(
        self,
        *,
        step: RuntimeStep,
        text_payload: str,
        run: FlowRun,
        context: dict[str, Any],
    ) -> None:
        if not step.output_config:
            return
        if not isinstance(step.output_config, dict):
            raise BadRequestException("Webhook output_config must be an object.")
        resolved_config = decrypt_step_headers_for_runtime(
            config=step.output_config,
            encryption_service=self.encryption_service,
        ) or {}
        if not isinstance(resolved_config, dict):
            raise BadRequestException("Webhook output_config must be an object.")
        url_raw = resolved_config.get("url")
        if not isinstance(url_raw, str) or not url_raw.strip():
            raise BadRequestException("Webhook output mode requires output_config.url.")
        url = self.variable_resolver.interpolate(url_raw, context).strip()
        timeout_seconds = self._resolve_http_timeout_seconds(
            resolved_config.get("timeout_seconds"),
            step_order=step.step_order,
            config_label="output_config",
        )
        headers = self._build_http_headers(
            resolved_config.get("headers"),
            context=context,
            step_order=step.step_order,
            config_label="output_config",
        )
        body_bytes, json_body = self._resolve_http_request_body(
            method="POST",
            config=resolved_config,
            context=context,
            step_order=step.step_order,
            config_label="output_config",
        )
        if body_bytes is None and json_body is None:
            body_bytes = text_payload.encode("utf-8")
        idempotency = hashlib.sha256(f"{run.id}:{step.step_id}".encode("utf-8")).hexdigest()
        headers["Idempotency-Key"] = idempotency
        start_time = time.monotonic()
        try:
            response = await self._send_http_request(
                method="POST",
                url=url,
                headers=headers,
                timeout_seconds=timeout_seconds,
                body_bytes=body_bytes,
                json_body=json_body,
                read_response_body=False,
            )
        except TypedIOValidationException as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            await self._audit_http_outbound(
                run=run, step=step, url=url, method="POST",
                call_type="webhook_delivery", outcome=Outcome.FAILURE,
                error_message=str(exc), duration_ms=duration_ms,
            )
            raise BadRequestException(str(exc)) from exc
        except httpx.TimeoutException as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            err_msg = f"Webhook delivery timed out after {timeout_seconds:g}s."
            await self._audit_http_outbound(
                run=run, step=step, url=url, method="POST",
                call_type="webhook_delivery", outcome=Outcome.FAILURE,
                error_message=err_msg, duration_ms=duration_ms,
            )
            raise BadRequestException(err_msg) from exc
        except httpx.HTTPError as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            err_msg = f"Webhook delivery failed: {exc}"
            await self._audit_http_outbound(
                run=run, step=step, url=url, method="POST",
                call_type="webhook_delivery", outcome=Outcome.FAILURE,
                error_message=err_msg, duration_ms=duration_ms,
            )
            raise BadRequestException(err_msg) from exc
        duration_ms = (time.monotonic() - start_time) * 1000
        if response.status_code >= 400:
            err_msg = f"Webhook delivery returned status {response.status_code}."
            await self._audit_http_outbound(
                run=run, step=step, url=url, method="POST",
                call_type="webhook_delivery", outcome=Outcome.FAILURE,
                error_message=err_msg, status_code=response.status_code,
                duration_ms=duration_ms,
            )
            raise BadRequestException(err_msg)
        await self._audit_http_outbound(
            run=run, step=step, url=url, method="POST",
            call_type="webhook_delivery", outcome=Outcome.SUCCESS,
            status_code=response.status_code, duration_ms=duration_ms,
        )

    async def _process_typed_output(
        self,
        *,
        full_text: str,
        step: RuntimeStep,
        run: FlowRun,
    ) -> tuple[dict[str, Any] | list[Any] | None, list[dict[str, Any]] | None]:
        """Process typed output: JSON parsing, contract validation, document rendering."""
        from intric.flows.output_processing import (
            compile_validators,
            parse_json_output,
        )
        from intric.flows.runtime.document_renderer import render_document

        structured_output = None
        artifacts = None

        compiled = compile_validators([step])

        if step.output_type == "json":
            structured_output = parse_json_output(full_text)
            validator = compiled.get(("output", step.step_order))
            if validator:
                from intric.flows.output_processing import validate_against_contract
                validate_against_contract(
                    structured_output, step.output_contract or {},
                    label=f"Step {step.step_order} output",
                )

        elif step.output_type in ("pdf", "docx"):
            if step.output_contract:
                pre_render_data = parse_json_output(full_text)
                from intric.flows.output_processing import validate_against_contract
                validate_against_contract(
                    pre_render_data, step.output_contract,
                    label=f"Step {step.step_order} output (pre-render)",
                )
            blob, mimetype, filename = render_document(
                full_text, step.output_type, step_order=step.step_order
            )
            file_record = await self.file_repo.add(
                FileCreate(
                    file_type=FileType.DOCUMENT,
                    blob=blob,
                    name=filename,
                    mimetype=mimetype,
                    checksum=hashlib.sha256(blob).hexdigest(),
                    size=len(blob),
                    user_id=self.user.id,
                    tenant_id=run.tenant_id,
                )
            )
            artifacts = [{
                "file_id": str(file_record.id),
                "name": filename,
                "mimetype": mimetype,
                "size": len(blob),
            }]

        return structured_output, artifacts

    async def _apply_output_cap(
        self,
        *,
        text: str,
        run: FlowRun,
        step: RuntimeStep,
    ) -> tuple[str, list[UUID]]:
        encoded = text.encode("utf-8")
        if len(encoded) <= self.max_inline_text_bytes:
            return text, []

        if run.user_id is None:
            return text[:4096], []

        file_row = await self.file_repo.add(
            FileCreate(
                name=f"flow-{run.id}-step-{step.step_order}-output.txt",
                checksum=hashlib.sha256(encoded).hexdigest(),
                size=len(encoded),
                mimetype="text/plain",
                file_type=FileType.TEXT,
                text=text,
                user_id=run.user_id,
                tenant_id=run.tenant_id,
            )
        )
        return text[:4096], [file_row.id]

    @staticmethod
    def _parse_runtime_steps(definition_json: dict[str, Any]) -> list[RuntimeStep]:
        steps = definition_json.get("steps")
        if not isinstance(steps, list):
            raise BadRequestException("Flow definition snapshot is missing steps.")
        parsed: list[RuntimeStep] = []
        for item in steps:
            if not isinstance(item, dict):
                raise BadRequestException("Invalid step definition in flow snapshot.")
            input_source = str(item.get("input_source", "flow_input"))
            if input_source not in FlowRunExecutor._ALLOWED_INPUT_SOURCES:
                raise BadRequestException(f"Unsupported input source '{input_source}'.")
            raw_input_config = item.get("input_config")
            if input_source in {"http_get", "http_post"}:
                if not isinstance(raw_input_config, dict):
                    raise BadRequestException("HTTP input source requires input_config object.")
                raw_headers = raw_input_config.get("headers")
                if raw_headers is not None and not isinstance(raw_headers, dict):
                    raise BadRequestException("HTTP input_config.headers must be an object.")
            elif raw_input_config is not None and not isinstance(raw_input_config, dict):
                raise BadRequestException("Step input_config must be an object.")
            output_mode = str(item.get("output_mode", "pass_through"))
            if output_mode not in FlowRunExecutor._ALLOWED_OUTPUT_MODES:
                raise BadRequestException(f"Unsupported output mode '{output_mode}'.")
            raw_output_config = item.get("output_config")
            if raw_output_config is not None and not isinstance(raw_output_config, dict):
                raise BadRequestException("Webhook output_config must be an object.")
            if isinstance(raw_output_config, dict):
                raw_headers = raw_output_config.get("headers")
                if raw_headers is not None and not isinstance(raw_headers, dict):
                    raise BadRequestException("Webhook output_config.headers must be an object.")
            try:
                step_id = UUID(str(item["step_id"]))
                assistant_id = UUID(str(item["assistant_id"]))
                step_order = int(item["step_order"])
            except (KeyError, TypeError, ValueError) as exc:
                raise BadRequestException("Invalid step identifiers in flow snapshot.") from exc
            parsed.append(
                RuntimeStep(
                    step_id=step_id,
                    step_order=step_order,
                    assistant_id=assistant_id,
                    user_description=str(item.get("user_description")).strip()
                    if isinstance(item.get("user_description"), str)
                    else None,
                    input_source=input_source,
                    input_bindings=item.get("input_bindings"),
                    input_config=raw_input_config,
                    output_mode=output_mode,
                    output_config=raw_output_config,
                    output_type=str(item.get("output_type", "text")),
                    output_contract=item.get("output_contract"),
                    input_type=str(item.get("input_type", "text")),
                    input_contract=item.get("input_contract"),
                )
            )
        chain_violation = find_first_step_chain_violation(parsed)
        if chain_violation is not None:
            raise BadRequestException(chain_violation.message)
        return parsed

    @staticmethod
    def _build_output_payload(output: StepExecutionOutput) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": output.persisted_text,
            "generated_file_ids": [str(file_id) for file_id in output.generated_file_ids],
            "file_ids": [str(file_id) for file_id in output.generated_file_ids],
            "webhook_delivered": False,
        }
        if output.structured_output is not None:
            payload["structured"] = output.structured_output
        if output.artifacts:
            payload["artifacts"] = output.artifacts
        return payload

    @staticmethod
    def _effective_model_parameters(assistant: Any) -> dict[str, Any]:
        kwargs = assistant.completion_model_kwargs.model_dump(exclude_none=True)  # type: ignore[attr-defined]
        completion_model = assistant.completion_model  # type: ignore[attr-defined]
        return {
            "model_id": str(completion_model.id) if completion_model and completion_model.id else None,
            "model_name": completion_model.name if completion_model else None,
            "provider": getattr(completion_model, "provider_type", None),
            **kwargs,
        }

    @staticmethod
    def _execution_hash(
        *,
        run_id: UUID,
        step_id: UUID,
        prompt: str,
        model_parameters: dict[str, Any],
    ) -> str:
        payload = json.dumps(
            {
                "run_id": str(run_id),
                "step_id": str(step_id),
                "prompt": prompt,
                "model_parameters": model_parameters,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def _commit(self) -> None:
        await self.flow_repo.session.commit()

    async def _rollback(self) -> None:
        await self.flow_repo.session.rollback()
