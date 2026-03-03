from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any
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
from intric.flows.type_policies import INPUT_TYPE_POLICIES
from intric.flows.variable_resolver import FlowVariableResolver
from intric.main.exceptions import BadRequestException, TypedIOValidationException
from intric.settings.encryption_service import EncryptionService
from intric.spaces.space_repo import SpaceRepository
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.files.file_repo import FileRepository
from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.users.user import UserInDB


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
    artifacts: list[dict[str, Any]] | None = None


@dataclass
class StepInputValue:
    """Typed step input — carries text, files, or structured data."""
    text: str
    files: list[Any] | None = None
    structured: dict[str, Any] | list[Any] | None = None
    raw_extracted_text: str = ""
    input_source: str = "flow_input"
    used_question_binding: bool = False
    legacy_prompt_binding_used: bool = False


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
        self.variable_resolver = FlowVariableResolver()

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
                        {"contract_validation": output.contract_validation}
                        if output.contract_validation is not None
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
                    await self._deliver_webhook(
                        step=step,
                        text_payload=output.full_text,
                        run=latest_run,
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
                "source_text": step_input.text,
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
            source_text=step_input.text,
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
        )

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
            if raw_file_ids:
                requested_ids = [UUID(fid) for fid in raw_file_ids]
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
                if step.input_type == "document" and files:
                    extracted = [f.text for f in files if f.text]
                    logger.info(
                        "flow_executor.document_text_extracted run_id=%s step_order=%d file_count=%d extracted_count=%d",
                        run.id, step.step_order, len(files), len(extracted),
                    )
                    if extracted:
                        input_text = "\n\n".join(extracted)
                    # Capture raw extraction before bindings can override
                    raw_extracted_text = input_text

        # For json input, prefer structured data from previous step
        structured = None
        if step.input_type == "json":
            if step.input_source == "previous_step":
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

        return StepInputValue(
            text=input_text,
            files=files,
            structured=structured,
            raw_extracted_text=raw_extracted_text,
            input_source=step.input_source,
            used_question_binding=used_question_binding,
            legacy_prompt_binding_used=legacy_prompt_binding_used,
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
                return str(previous.output_payload_json.get("text", ""))
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

    async def _deliver_webhook(self, *, step: RuntimeStep, text_payload: str, run: FlowRun) -> None:
        if not step.output_config:
            return
        if not isinstance(step.output_config, dict):
            raise BadRequestException("Webhook output_config must be an object.")
        url = str(step.output_config.get("url", "")).strip()
        if not url:
            raise BadRequestException("Webhook output mode requires output_config.url.")
        resolved_config = decrypt_step_headers_for_runtime(
            config=step.output_config,
            encryption_service=self.encryption_service,
        ) or {}
        if not isinstance(resolved_config, dict):
            raise BadRequestException("Webhook output_config must be an object.")
        headers_raw = resolved_config.get("headers")
        if headers_raw is not None and not isinstance(headers_raw, dict):
            raise BadRequestException("Webhook output_config.headers must be an object.")
        headers = {
            str(key): str(value)
            for key, value in (headers_raw or {}).items()
            if value is not None
        }
        idempotency = hashlib.sha256(f"{run.id}:{step.step_id}".encode("utf-8")).hexdigest()
        headers["Idempotency-Key"] = idempotency
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, content=text_payload.encode("utf-8"))
            response.raise_for_status()

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
                    input_config=item.get("input_config"),
                    output_mode=output_mode,
                    output_config=raw_output_config,
                    output_type=str(item.get("output_type", "text")),
                    output_contract=item.get("output_contract"),
                    input_type=str(item.get("input_type", "text")),
                    input_contract=item.get("input_contract"),
                )
            )
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
