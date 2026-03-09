from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
import sqlalchemy as sa

logger = logging.getLogger(__name__)

from intric.database.tables.flow_tables import Flows
from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResult,
)
from intric.flows.flow_repo import FlowRepository
from intric.flows.flow_run_repo import FlowRunRepository
from intric.flows.flow_version_repo import FlowVersionRepository
from intric.flows.flow_template_asset_service import FlowTemplateAssetService
from intric.flows.variable_resolver import FlowVariableResolver
from intric.flows.runtime.http_runtime import FlowHttpRuntimeHelper, IPAddress
from intric.flows.runtime.http_orchestration import (
    FlowHttpOrchestrationDeps,
    deliver_webhook as deliver_webhook_orchestrated,
    resolve_http_input_source_text as resolve_http_input_source_text_orchestrated,
)
from intric.flows.runtime.http_audit import (
    HttpAuditDeps,
    audit_http_outbound as audit_http_outbound_runtime,
)
from intric.flows.runtime.execution_state_builder import build_run_execution_state
from intric.flows.runtime.output_runtime import (
    OutputRuntimeDeps,
    process_typed_output as process_typed_output_runtime,
)
from intric.flows.runtime.rag_retrieval import RagRetrievalDeps, retrieve_rag_chunks
from intric.flows.runtime.run_outcome import determine_run_outcome
from intric.flows.runtime.claim_resolution import resolve_step_claim
from intric.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
)
from intric.flows.runtime.step_definition_parser import parse_runtime_steps
from intric.flows.runtime.step_input_resolution import (
    StepInputResolutionDeps,
    resolve_step_input as resolve_step_input_runtime,
)
from intric.flows.runtime.step_result_builder import (
    build_default_failed_input_payload,
    with_webhook_delivery_status,
)
from intric.flows.runtime.step_execution_runtime import (
    StepExecutionRuntimeDeps,
    attach_typed_failure_context,
    build_output_payload,
    complete_step_execution,
    effective_model_parameters,
    execution_hash,
    is_json_mode_rejection,
    json_mode_cache_key,
    prepare_step_execution,
)
from intric.flows.runtime.step_attempt_runtime import (
    build_generic_failure_plan,
    build_step_gate_decision,
    build_step_success_plan,
    build_typed_failure_plan,
)
from intric.flows.runtime.template_fill_runtime import (
    TemplateFillRuntimeDeps,
    execute_template_fill_step,
)
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, TypedIOValidationException
from intric.settings.encryption_service import EncryptionService
from intric.spaces.space_repo import SpaceRepository
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.files.file_models import FileCreate, FileType
from intric.files.file_repo import FileRepository
from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.audit.domain.outcome import Outcome
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService
    from intric.assistants.references import ReferencesService
    from intric.files.transcriber import Transcriber

class FlowRunExecutor:
    """Executes a version-pinned flow run sequentially with CAS step claims."""

    _TERMINAL_STATUSES = {
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
        FlowRunStatus.CANCELLED,
    }
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
        template_asset_service: FlowTemplateAssetService,
        encryption_service: EncryptionService,
        max_inline_text_bytes: int,
        audit_service: AuditService | None = None,
        references_service: ReferencesService | None = None,
        transcriber: Transcriber | None = None,
        max_audio_files: int = 10,
        max_generic_files: int | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.flow_version_repo = flow_version_repo
        self.space_repo = space_repo
        self.completion_service = completion_service
        self.file_repo = file_repo
        self.template_asset_service = template_asset_service
        self.encryption_service = encryption_service
        self.max_inline_text_bytes = max_inline_text_bytes
        self.audit_service = audit_service
        self.references_service = references_service
        self.transcriber = transcriber
        self.variable_resolver = FlowVariableResolver()
        settings = get_settings()
        self.http_request_timeout_seconds = float(settings.flow_http_request_timeout_seconds)
        self.http_max_timeout_seconds = float(settings.flow_http_max_timeout_seconds)
        self.http_allow_private_networks = bool(settings.flow_http_allow_private_networks)
        self.http_runtime = FlowHttpRuntimeHelper(
            variable_resolver=self.variable_resolver,
            request_timeout_seconds=self.http_request_timeout_seconds,
            max_timeout_seconds=self.http_max_timeout_seconds,
            allow_private_networks=self.http_allow_private_networks,
        )
        self.rag_retrieval_timeout_seconds = 30
        self.rag_max_reference_sources = 25
        self.rag_max_chunks_per_source = 5
        self.max_audio_files = max_audio_files
        self.max_generic_files = max_generic_files

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
        version_metadata = (
            version.definition_json.get("metadata_json")
            if isinstance(version.definition_json, dict)
            else None
        )

        persisted_results = await self.flow_run_repo.list_step_results(run_id=run_id, tenant_id=tenant_id)
        state = build_run_execution_state(steps=steps, persisted_results=persisted_results)

        logger.info("flow_executor.steps_parsed run_id=%s step_count=%d", run_id, len(steps))
        for step in sorted(steps, key=lambda item: item.step_order):
            latest_run = await self.flow_run_repo.get(run_id=run_id, tenant_id=tenant_id, flow_id=flow_id)
            flow_active = await self._flow_is_active(flow_id=flow_id, tenant_id=tenant_id)
            preclaim_decision = build_step_gate_decision(
                latest_run_status=latest_run.status,
                flow_active=flow_active,
                claim_resolution=None,
                step_id=step.step_id,
            )
            if preclaim_decision.action == "return":
                return preclaim_decision.result or {"status": "skipped", "reason": "unknown"}
            if preclaim_decision.action == "cancel_flow_deleted":
                await self.flow_run_repo.mark_pending_steps_cancelled(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    error_message=preclaim_decision.run_error_message or "Flow was deleted during execution.",
                )
                await self.flow_run_repo.update_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=FlowRunStatus.CANCELLED,
                    error_message=preclaim_decision.run_error_message,
                    from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                )
                await self._commit()
                return preclaim_decision.result or {"status": "cancelled", "reason": "flow_deleted"}

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
                claim_resolution = resolve_step_claim(
                    claimed=claimed,
                    existing=existing,
                    state=state,
                )
                postclaim_decision = build_step_gate_decision(
                    latest_run_status=latest_run.status,
                    flow_active=True,
                    claim_resolution=claim_resolution,
                    step_id=step.step_id,
                )
                if postclaim_decision.action == "return":
                    return postclaim_decision.result or {"status": "skipped", "reason": "unknown"}
                if postclaim_decision.action == "fail_step_missing":
                    await self.flow_run_repo.update_status(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        status=FlowRunStatus.FAILED,
                        error_message=postclaim_decision.run_error_message,
                        from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                    )
                    await self._commit()
                    return postclaim_decision.result or {"status": "failed", "error": "step_missing"}
                if postclaim_decision.action == "append_completed" and postclaim_decision.completed_result is not None:
                    state.append_completed(postclaim_decision.completed_result)
                    continue
                if postclaim_decision.action == "continue":
                    continue

            attempt_no = retry_count + 1
            try:
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
            except Exception:
                logger.exception(
                    "flow_executor.step_attempt_start_failed run_id=%s step_order=%d step_id=%s",
                    run_id,
                    step.step_order,
                    step.step_id,
                )
                await self._rollback()
                failure_plan = build_generic_failure_plan(
                    claimed=claimed,
                    public_error=f"Flow step {step.step_order} execution failed.",
                )
                await self.flow_repo.save_step_result(run_id, failure_plan.failed_result, tenant_id=tenant_id)
                await self.flow_run_repo.update_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=FlowRunStatus.FAILED,
                    error_message=failure_plan.run_error_message,
                    from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                )
                await self._commit()
                return failure_plan.return_result

            logger.info(
                "flow_executor.step_start run_id=%s step_order=%d step_id=%s input_type=%s output_type=%s",
                run_id, step.step_order, step.step_id, step.input_type, step.output_type,
            )
            try:
                output = await self._execute_step(
                    step=step,
                    run=latest_run,
                    state=state,
                    version_metadata=version_metadata,
                )
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
                    failed_input_payload = build_default_failed_input_payload(
                        input_source=step.input_source
                    )
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
                failed_prompt = getattr(typed_exc, "effective_prompt", None)
                failure_plan = build_typed_failure_plan(
                    claimed=claimed,
                    error_code=typed_exc.code,
                    error_message=str(typed_exc),
                    input_payload_json=failed_input_payload if isinstance(failed_input_payload, dict) else None,
                    effective_prompt=failed_prompt if isinstance(failed_prompt, str) else None,
                )
                await self.flow_run_repo.finish_attempt(
                    run_id=run_id,
                    step_id=step.step_id,
                    attempt_no=attempt_no,
                    tenant_id=tenant_id,
                    status=failure_plan.attempt_status,
                    error_code=failure_plan.error_code,
                    error_message=failure_plan.error_message,
                )
                await self.flow_repo.save_step_result(run_id, failure_plan.failed_result, tenant_id=tenant_id)
                await self.flow_run_repo.update_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=FlowRunStatus.FAILED,
                    error_message=failure_plan.run_error_message,
                    from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                )
                await self._commit()
                return failure_plan.return_result
            except Exception as exc:
                logger.exception(
                    "flow_executor.step_failed run_id=%s step_order=%d error=%s",
                    run_id, step.step_order, str(exc),
                )
                public_error = f"Flow step {step.step_order} execution failed."
                await self._rollback()
                failure_plan = build_generic_failure_plan(
                    claimed=claimed,
                    public_error=public_error,
                )
                await self.flow_run_repo.finish_attempt(
                    run_id=run_id,
                    step_id=step.step_id,
                    attempt_no=attempt_no,
                    tenant_id=tenant_id,
                    status=failure_plan.attempt_status,
                    error_code=failure_plan.error_code,
                    error_message=failure_plan.error_message,
                )
                await self.flow_repo.save_step_result(run_id, failure_plan.failed_result, tenant_id=tenant_id)
                await self.flow_run_repo.update_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=FlowRunStatus.FAILED,
                    error_message=failure_plan.run_error_message,
                    from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
                )
                await self._commit()
                return failure_plan.return_result

            success_plan = build_step_success_plan(
                claimed=claimed,
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step=step,
                output=output,
                output_payload_json=build_output_payload(output),
                execution_hash=execution_hash(
                    run_id=run_id,
                    step_id=step.step_id,
                    prompt=output.effective_prompt,
                    model_parameters=output.model_parameters_json,
                ),
            )
            step_result = success_plan.step_result
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

            if success_plan.should_deliver_webhook:
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
                    step_result = with_webhook_delivery_status(
                        step_result=step_result,
                        delivered=False,
                        error=str(exc),
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

                step_result = with_webhook_delivery_status(
                    step_result=step_result,
                    delivered=True,
                )
                await self.flow_repo.save_step_result(run_id, step_result, tenant_id=tenant_id)
                await self._commit()

        results = await self.flow_run_repo.list_step_results(run_id=run_id, tenant_id=tenant_id)
        outcome = determine_run_outcome(results=results)
        if outcome.result_status == "skipped":
            return {"status": "skipped", "reason": outcome.reason}

        await self.flow_run_repo.update_status(
            run_id=run_id,
            tenant_id=tenant_id,
            status=FlowRunStatus(outcome.flow_status),
            error_message=outcome.error_message,
            output_payload_json=outcome.output_payload_json,
            from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
        )
        await self._commit()
        return {"status": outcome.result_status}

    async def _execute_step(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState | None = None,
        version_metadata: dict[str, Any] | None = None,
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
        logger.debug("flow_executor.resolving_input run_id=%s step_order=%d", run.id, step.step_order)
        if step.output_mode == "template_fill":
            template_fill_deps = TemplateFillRuntimeDeps(
                variable_resolver=self.variable_resolver,
                file_repo=self.file_repo,
                template_asset_service=self.template_asset_service,
                apply_output_cap=self._apply_output_cap,
                user_id=self.user.id,
                logger=logger,
            )
            return await execute_template_fill_step(
                step=step,
                run=run,
                state=state,
                deps=template_fill_deps,
            )
        execution_deps = StepExecutionRuntimeDeps(
            variable_resolver=self.variable_resolver,
            completion_service=self.completion_service,
            load_assistant=self._load_assistant,
            resolve_step_input=self._resolve_step_input,
            retrieve_rag_chunks=self._retrieve_rag_chunks,
            process_typed_output=self._process_typed_output,
            apply_output_cap=self._apply_output_cap,
            attach_typed_failure_context=attach_typed_failure_context,
            effective_model_parameters=effective_model_parameters,
            json_mode_cache_key=json_mode_cache_key,
            is_json_mode_rejection=is_json_mode_rejection,
            count_tokens=count_tokens,
            logger=logger,
            rag_retrieval_timeout_seconds=self.rag_retrieval_timeout_seconds,
        )
        prepared = await prepare_step_execution(
            step=step,
            run=run,
            state=state,
            version_metadata=version_metadata,
            deps=execution_deps,
        )
        await self._commit()
        return await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=execution_deps,
        )

    async def _retrieve_rag_chunks(
        self,
        *,
        assistant: Any,
        question: str,
        run_id: UUID,
        step_order: int,
    ) -> tuple[list[Any], dict[str, Any], list[StepDiagnostic]]:
        deps = RagRetrievalDeps(
            references_service=self.references_service,
            rag_retrieval_timeout_seconds=self.rag_retrieval_timeout_seconds,
            rag_max_reference_sources=self.rag_max_reference_sources,
            rag_max_chunks_per_source=self.rag_max_chunks_per_source,
            logger=logger,
        )
        return await retrieve_rag_chunks(
            assistant=assistant,
            question=question,
            run_id=run_id,
            step_order=step_order,
            deps=deps,
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
        version_metadata: dict[str, Any] | None = None,
    ) -> StepInputValue:
        deps = StepInputResolutionDeps(
            variable_resolver=self.variable_resolver,
            resolve_http_input_source_text=self._resolve_http_input_source_text,
            file_repo=self.file_repo,
            user_id=self.user.id,
            transcriber=self.transcriber,
            space_repo=self.space_repo,
            flow_run_repo=self.flow_run_repo,
            audit_service=self.audit_service,
            actor=self.user,
            max_generic_files=self.max_generic_files,
            max_audio_files=self.max_audio_files,
            max_inline_text_bytes=self.max_inline_text_bytes,
            logger=logger,
        )
        return await resolve_step_input_runtime(
            step=step,
            context=context,
            run=run,
            prior_results=prior_results,
            assistant_prompt_text=assistant_prompt_text,
            state=state,
            version_metadata=version_metadata,
            deps=deps,
        )

    async def _resolve_http_input_source_text(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        context: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | list[Any] | None]:
        deps = FlowHttpOrchestrationDeps(
            encryption_service=self.encryption_service,
            variable_resolver=self.variable_resolver,
            resolve_timeout_seconds=self.http_runtime.resolve_timeout_seconds,
            build_headers=self.http_runtime.build_headers,
            resolve_request_body=self.http_runtime.resolve_request_body,
            read_response_text=self.http_runtime.read_response_text,
            send_http_request=self._send_http_request,
            audit_http_outbound=self._audit_http_outbound,
        )
        return await resolve_http_input_source_text_orchestrated(
            step=step,
            run=run,
            context=context,
            deps=deps,
        )

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
        return await self.http_runtime.send_request(
            method=method,
            url=url,
            headers=headers,
            timeout_seconds=timeout_seconds,
            body_bytes=body_bytes,
            json_body=json_body,
            read_response_body=read_response_body,
            preflight_resolved_ips=preflight_resolved_ips,
            assert_connected_peer_allowed=self._assert_http_connected_peer_allowed,
        )

    async def _assert_http_url_allowed(self, url: str) -> set[IPAddress] | None:
        return await self.http_runtime.assert_url_allowed(url)

    def _assert_http_connected_peer_allowed(
        self,
        *,
        response: httpx.Response,
        preflight_resolved_ips: set[IPAddress] | None,
    ) -> None:
        self.http_runtime.assert_connected_peer_allowed(
            response=response,
            preflight_resolved_ips=preflight_resolved_ips,
        )

    async def _load_assistant(self, assistant_id: UUID, state: RunExecutionState | None = None) -> Any:
        if state and assistant_id in state.assistant_cache:
            return state.assistant_cache[assistant_id]
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        if state:
            state.assistant_cache[assistant_id] = assistant
        return assistant

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
        deps = HttpAuditDeps(
            audit_service=self.audit_service,
            user=self.user,
            logger=logger,
        )
        await audit_http_outbound_runtime(
            run=run,
            step=step,
            url=url,
            method=method,
            call_type=call_type,
            outcome=outcome,
            error_message=error_message,
            status_code=status_code,
            duration_ms=duration_ms,
            deps=deps,
        )

    async def _deliver_webhook(
        self,
        *,
        step: RuntimeStep,
        text_payload: str,
        run: FlowRun,
        context: dict[str, Any],
    ) -> None:
        deps = FlowHttpOrchestrationDeps(
            encryption_service=self.encryption_service,
            variable_resolver=self.variable_resolver,
            resolve_timeout_seconds=self.http_runtime.resolve_timeout_seconds,
            build_headers=self.http_runtime.build_headers,
            resolve_request_body=self.http_runtime.resolve_request_body,
            read_response_text=self.http_runtime.read_response_text,
            send_http_request=self._send_http_request,
            audit_http_outbound=self._audit_http_outbound,
        )
        await deliver_webhook_orchestrated(
            step=step,
            text_payload=text_payload,
            run=run,
            context=context,
            deps=deps,
        )

    async def _process_typed_output(
        self,
        *,
        full_text: str,
        step: RuntimeStep,
        run: FlowRun,
    ) -> tuple[dict[str, Any] | list[Any] | None, list[dict[str, Any]] | None]:
        from intric.flows.output_processing import (
            compile_validators,
            parse_json_output,
            validate_against_contract,
        )
        from intric.flows.runtime.document_renderer import render_document

        deps = OutputRuntimeDeps(
            file_repo=self.file_repo,
            user_id=self.user.id,
            compile_validators=compile_validators,
            parse_json_output=parse_json_output,
            validate_against_contract=validate_against_contract,
            render_document=render_document,
        )
        return await process_typed_output_runtime(
            full_text=full_text,
            step=step,
            run=run,
            deps=deps,
        )

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
        return parse_runtime_steps(definition_json)

    async def _commit(self) -> None:
        await self.flow_repo.session.commit()

    async def _rollback(self) -> None:
        await self.flow_repo.session.rollback()
