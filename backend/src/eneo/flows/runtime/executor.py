from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Sequence, assert_never, cast
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from eneo.audit.domain.outcome import Outcome
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.completion_models.infrastructure.context_builder import count_tokens
from eneo.files.file_models import FileCreate, FileType
from eneo.files.file_repo import FileRepository
from eneo.flows.application.flow_run_terminalization import (
    FlowRunTerminalizationResult,
    FlowRunTerminalizer,
)
from eneo.flows.assistant_execution_snapshot import (
    build_assistant_execution_snapshot,
    validate_assistant_execution_snapshot,
)
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
)
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    resolve_flow_mapped_execution_policy,
)
from eneo.flows.domain.rerun_exceptions import (
    FlowRunRerunAttemptLineageConflictError,
    FlowRunRerunMultipleActiveOperationsError,
)
from eneo.flows.domain.review_checkpoint_exceptions import (
    FLOW_REVIEW_CHECKPOINT_OPEN_TERMINAL_INVARIANT_CLASSES,
    FlowReviewCheckpointOpenTerminalInvariantFailure,
    FlowReviewCheckpointRunNotRunningError,
    FlowReviewMultipleActiveCheckpointsError,
)
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
)
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.flows.enums import (
    FlowOutputMode,
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunRerunInvalidationRole,
)
from eneo.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FLOW_TYPED_IO_ERROR_CODES,
    FlowApiErrorCode,
)
from eneo.flows.flow_review_policy import FlowStepReviewPolicy
from eneo.flows.flow_run_error import FlowRunError, FlowRunErrorDetails
from eneo.flows.flow_run_provenance import (
    AttemptStartProvenance,
    FlowAttemptProvenance,
    LlmProvenance,
    ModelParameterSnapshot,
    normalize_json_preview,
    normalize_text_preview,
)
from eneo.flows.flow_run_step_result_file import build_step_result_file_references
from eneo.flows.flow_runtime_policy import (
    FlowRuntimePolicy,
    default_flow_runtime_policy,
    resolve_step_timeout_seconds,
)
from eneo.flows.flow_security_classification import (
    evaluate_step_security_classification,
)
from eneo.flows.flow_template_asset_repo import FlowTemplateAssetRepository
from eneo.flows.infrastructure.flow_provider_call_recorder import (
    FlowProviderCallRecorder,
    ProviderCallEvidencePersistenceError,
)
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_rerun_repo import (
    FlowRunActiveRerunOperation,
    FlowRunRerunRepository,
)
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.principal import FlowPrincipal
from eneo.flows.published_definition import (
    PublishedDefinitionChecksumMismatchError,
    parse_verified_published_definition,
)
from eneo.flows.runtime.claim_resolution import resolve_step_claim
from eneo.flows.runtime.document_rendering import DocumentRenderService
from eneo.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
)
from eneo.flows.runtime.document_rendering.service import (
    default_document_render_service,
)
from eneo.flows.runtime.execution_state_builder import build_run_execution_state
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.flow_runtime_trace import trace_flow_step
from eneo.flows.runtime.http_audit import (
    HttpAuditDeps,
)
from eneo.flows.runtime.http_audit import (
    audit_http_outbound as audit_http_outbound_runtime,
)
from eneo.flows.runtime.http_orchestration import (
    FlowHttpOrchestrationDeps,
)
from eneo.flows.runtime.http_orchestration import (
    resolve_http_input_source_text as resolve_http_input_source_text_orchestrated,
)
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper, IPAddress
from eneo.flows.runtime.output_runtime import (
    OutputRuntimeDeps,
    TypedOutputProcessingResult,
)
from eneo.flows.runtime.output_runtime import (
    process_typed_output as process_typed_output_runtime,
)
from eneo.flows.runtime.protocols import RuntimeAssistantProtocol
from eneo.flows.runtime.rag_retrieval import RagRetrievalDeps, retrieve_rag_chunks
from eneo.flows.runtime.run_outcome import finalize_run_from_current_results
from eneo.flows.runtime.step_attempt_runtime import (
    build_generic_failure_plan,
    build_step_gate_decision,
    build_step_success_plan,
    build_typed_failure_plan,
    build_typed_failure_run_error_message,
)
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import (
    FlowStepCancelledError,
    StepExecutionRuntimeDeps,
    build_output_payload,
    execution_hash,
    prepare_step_execution,
)
from eneo.flows.runtime.step_handlers import resolve_handler_mode
from eneo.flows.runtime.step_handlers.base import PreparedAssistantStep, StepHandler
from eneo.flows.runtime.step_handlers.compose_text import ComposeTextStepHandler
from eneo.flows.runtime.step_handlers.http_post import HttpPostStepHandler
from eneo.flows.runtime.step_handlers.pass_through import PassThroughStepHandler
from eneo.flows.runtime.step_handlers.render_verbatim import RenderVerbatimStepHandler
from eneo.flows.runtime.step_handlers.template_fill import TemplateFillStepHandler
from eneo.flows.runtime.step_handlers.transcribe_only import TranscribeOnlyStepHandler
from eneo.flows.runtime.step_input_resolution import (
    StepInputResolutionDeps,
)
from eneo.flows.runtime.step_input_resolution import (
    resolve_step_input as resolve_step_input_runtime,
)
from eneo.flows.runtime.step_result_builder import (
    build_default_failed_input_payload,
)
from eneo.flows.runtime.template_fill_runtime import (
    TemplateFillRuntimeDeps,
)
from eneo.flows.runtime_input import build_runtime_input_config
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    BadRequestException,
    ProviderCapabilityRejectedException,
    ProviderRejectedRequestException,
    TypedIOValidationException,
)
from eneo.settings.encryption_service import EncryptionService
from eneo.spaces.space_repo import SpaceRepository

if TYPE_CHECKING:
    from eneo.assistants.references import ReferencesService
    from eneo.audit.application.audit_service import AuditService
    from eneo.files.transcriber import Transcriber
    from eneo.spaces.space import Space


_RERUN_MULTIPLE_ACTIVE_OPERATIONS_RUN_ERROR_MESSAGE = (
    "Rerun failed because multiple active rerun operations exist."
)
_RERUN_ATTEMPT_LINEAGE_CONFLICT_RUN_ERROR_MESSAGE = (
    "Rerun failed because the invalidated step is already linked to another attempt."
)
_PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV = (
    "ENEO_TEST_FLOW_CRASH_AFTER_ATTEMPT_START_RUN_ID"
)
_PROCESS_TEST_CRASH_EXIT_CODE = 86
_PROVIDER_WORK_AMBIGUITY_DISCLOSURE = (
    "Provider work may or may not have started; rerunning can repeat provider work "
    "and spend."
)


def _with_provider_work_disclosure(message: str, *, step: RuntimeStep) -> str:
    if not step.may_call_completion_provider:
        return message
    return f"{message.rstrip()} {_PROVIDER_WORK_AMBIGUITY_DISCLOSURE}"


def _typed_io_failure_code(raw_code: str | None) -> FlowApiErrorCode:
    if raw_code is None:
        return FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED
    try:
        code = FlowApiErrorCode(raw_code)
    except ValueError:
        return FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED
    if code in FLOW_TYPED_IO_ERROR_CODES:
        return code
    return FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED


def _flow_api_error_code_or_default(
    raw_code: str | None,
    *,
    default_code: FlowApiErrorCode,
) -> FlowApiErrorCode:
    if raw_code is None:
        return default_code
    try:
        code = FlowApiErrorCode(raw_code)
    except ValueError:
        logger.warning(
            "flow_executor.bad_request_uncataloged_code code=%s default_code=%s",
            raw_code,
            default_code.value,
        )
        return default_code
    if code in FLOW_RUN_TERMINAL_ERROR_CODES:
        return code
    logger.warning(
        "flow_executor.bad_request_non_terminal_code code=%s default_code=%s",
        raw_code,
        default_code.value,
    )
    return default_code


def _utf8_prefix(text: str, *, max_bytes: int) -> str:
    return text.encode("utf-8")[: max(0, max_bytes)].decode("utf-8", errors="ignore")


@dataclass(frozen=True)
class FlowRunExecutorConfig:
    max_inline_text_bytes: int
    max_audio_files: int = 10
    max_generic_files: int | None = None
    http_request_timeout_seconds: float = 30.0
    http_max_timeout_seconds: float = 30.0
    http_allow_private_networks: bool = False
    runtime_policy: FlowRuntimePolicy = field(
        default_factory=default_flow_runtime_policy
    )
    mapped_execution_policy: FlowMappedExecutionPolicy = field(
        default_factory=lambda: resolve_flow_mapped_execution_policy(None)
    )
    rag_retrieval_timeout_seconds: float = 30.0
    rag_max_reference_sources: int = 25
    rag_max_chunks_per_source: int = 5
    document_render_limits: DocumentRenderLimits = field(
        default_factory=lambda: DEFAULT_DOCUMENT_RENDER_LIMITS
    )

    @classmethod
    def from_settings(
        cls,
        *,
        max_inline_text_bytes: int,
        max_audio_files: int = 10,
        max_generic_files: int | None = None,
        document_render_limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS,
        runtime_policy: FlowRuntimePolicy | None = None,
        mapped_execution_policy: FlowMappedExecutionPolicy | None = None,
    ) -> "FlowRunExecutorConfig":
        settings = get_settings()
        resolved_runtime_policy = runtime_policy or default_flow_runtime_policy(
            defaults=settings
        )
        return cls(
            max_inline_text_bytes=max_inline_text_bytes,
            max_audio_files=max_audio_files,
            max_generic_files=max_generic_files,
            http_request_timeout_seconds=float(
                settings.flow_http_request_timeout_seconds
            ),
            http_max_timeout_seconds=float(settings.flow_http_max_timeout_seconds),
            http_allow_private_networks=bool(settings.flow_http_allow_private_networks),
            runtime_policy=resolved_runtime_policy,
            mapped_execution_policy=(
                mapped_execution_policy or resolve_flow_mapped_execution_policy(None)
            ),
            document_render_limits=document_render_limits,
        )

    def step_deadline_seconds(self, step: RuntimeStep) -> float:
        return float(
            resolve_step_timeout_seconds(
                step_timeout_seconds=step.timeout_seconds,
                policy=self.runtime_policy,
            )
        )


def _requested_model_from_assistant(
    assistant: RuntimeAssistantProtocol,
) -> str | None:
    completion_model = getattr(assistant, "completion_model", None)
    if completion_model is None:
        return None
    requested = getattr(completion_model, "litellm_model_name", None) or getattr(
        completion_model, "name", None
    )
    return requested if isinstance(requested, str) else None


def _provider_from_assistant(assistant: RuntimeAssistantProtocol) -> str | None:
    completion_model = getattr(assistant, "completion_model", None)
    if completion_model is None:
        return None
    provider = getattr(completion_model, "provider_type", None)
    return provider if isinstance(provider, str) else None


def _model_parameter_snapshot(
    assistant: RuntimeAssistantProtocol,
) -> ModelParameterSnapshot:
    kwargs = assistant.completion_model_kwargs.model_dump(exclude_none=False)
    temperature = kwargs.get("temperature")
    top_p = kwargs.get("top_p")
    reasoning_effort = kwargs.get("reasoning_effort")
    verbosity = kwargs.get("verbosity")
    return ModelParameterSnapshot(
        temperature=temperature
        if isinstance(temperature, int | float) and not isinstance(temperature, bool)
        else None,
        top_p=top_p
        if isinstance(top_p, int | float) and not isinstance(top_p, bool)
        else None,
        reasoning_effort=reasoning_effort
        if isinstance(reasoning_effort, str)
        else None,
        verbosity=verbosity if isinstance(verbosity, str) else None,
    )


def _attempt_start_for_step(
    *,
    state: RunExecutionState | None,
    step: RuntimeStep,
) -> AttemptStartProvenance | None:
    if state is None:
        return None
    return state.attempt_start_by_step.get(step.step_id)


def _pre_attempt_start_model_from_state_cache(
    *,
    state: RunExecutionState | None,
    step: RuntimeStep,
) -> tuple[str | None, str | None]:
    # Preparation can fail after the assistant is loaded but before
    # attempt_start is persisted; preserve model triage data in that window.
    if state is None:
        return None, None
    assistant = state.assistant_cache.get(step.assistant_id)
    if assistant is None:
        return None, None
    return (
        _requested_model_from_assistant(assistant),
        _provider_from_assistant(assistant),
    )


def _build_incomplete_attempt_provenance(
    *,
    state: RunExecutionState | None,
    step: RuntimeStep,
) -> dict[str, Any] | None:
    attempt_start = _attempt_start_for_step(state=state, step=step)
    if attempt_start is None:
        return None
    return FlowAttemptProvenance(attempt_start=attempt_start).to_payload()


def _build_attempt_provenance(
    *,
    step: RuntimeStep,
    output: StepExecutionOutput,
    step_result: FlowStepResult,
    attempt_start: AttemptStartProvenance | None = None,
) -> dict[str, Any]:
    provenance_payload: dict[str, Any] = {
        "llm": LlmProvenance(
            effective_prompt=normalize_text_preview(output.effective_prompt),
            model_parameters=output.model_parameters_json,
            tool_calls=normalize_json_preview(output.tool_calls_metadata)
            if output.tool_calls_metadata is not None
            else None,
            raw_completion_text=normalize_text_preview(output.raw_completion_text)
            if isinstance(output.raw_completion_text, str)
            and output.raw_completion_text
            else None,
        )
    }
    if attempt_start is not None:
        provenance_payload["attempt_start"] = attempt_start
    if output.rag_metadata is not None:
        provenance_payload["rag"] = output.rag_metadata
    if output.runtime_input_metadata is not None:
        provenance_payload["runtime_input"] = output.runtime_input_metadata
    if output.transcription_metadata is not None:
        provenance_payload["transcription"] = output.transcription_metadata
    if output.contract_validation is not None or output.diagnostics:
        provenance_payload["guards"] = {
            "contract_validation": output.contract_validation,
            "diagnostics": [
                {
                    "code": diagnostic.code,
                    "message": diagnostic.message,
                    "severity": diagnostic.severity,
                }
                for diagnostic in output.diagnostics
            ],
        }
    output_payload = step_result.output_payload_json or {}
    template_provenance = output_payload.get("template_provenance")
    if isinstance(template_provenance, dict):
        provenance_payload["template"] = template_provenance
    if output.artifacts or output.generated_file_ids:
        provenance_payload["artifacts"] = {
            "items": output.artifacts or [],
            "generated_file_ids": [
                str(file_id) for file_id in output.generated_file_ids
            ],
        }
    if step.input_source == "http_get":
        provenance_payload["http"] = {
            "input_source": step.input_source,
            "structured_input_present": output.source_text != "",
        }
    if step.output_mode == "http_post":
        provenance_payload["http"] = {
            **cast(dict[str, Any], provenance_payload.get("http", {})),
            "output_mode": step.output_mode,
        }
    if output.citation_sidecar is not None:
        provenance_payload["citations"] = output.citation_sidecar
    return FlowAttemptProvenance.model_validate(provenance_payload).to_payload()


class FlowRunExecutor:
    """Executes a version-pinned flow run sequentially with CAS step claims."""

    def __init__(
        self,
        *,
        runtime_actor: FlowRunActor,
        session: AsyncSession,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        flow_run_rerun_repo: FlowRunRerunRepository,
        flow_run_review_checkpoint_repo: FlowRunReviewCheckpointRepository,
        flow_version_repo: FlowVersionRepository,
        space_repo: SpaceRepository,
        completion_service: CompletionService,
        file_repo: FileRepository,
        template_asset_repo: FlowTemplateAssetRepository,
        encryption_service: EncryptionService,
        flow_run_terminalizer: FlowRunTerminalizer,
        max_inline_text_bytes: int | None = None,
        audit_service: AuditService | None = None,
        webhook_delivery_repo: FlowRunWebhookDeliveryRepository | None = None,
        references_service: ReferencesService | None = None,
        transcriber: Transcriber | None = None,
        max_audio_files: int = 10,
        max_generic_files: int | None = None,
        config: FlowRunExecutorConfig | None = None,
    ) -> None:
        resolved_config = config
        if resolved_config is None:
            if max_inline_text_bytes is None:
                raise TypeError(
                    "FlowRunExecutor requires max_inline_text_bytes or config."
                )
            resolved_config = FlowRunExecutorConfig.from_settings(
                max_inline_text_bytes=max_inline_text_bytes,
                max_audio_files=max_audio_files,
                max_generic_files=max_generic_files,
            )

        self.runtime_actor = runtime_actor
        self.principal = runtime_actor.principal
        self.session = session
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.flow_run_rerun_repo = flow_run_rerun_repo
        self.flow_run_review_checkpoint_repo = flow_run_review_checkpoint_repo
        self.flow_run_terminalizer = flow_run_terminalizer
        self.webhook_delivery_repo = (
            webhook_delivery_repo
            if webhook_delivery_repo is not None
            else FlowRunWebhookDeliveryRepository(session=session)
        )
        self.flow_version_repo = flow_version_repo
        self.space_repo = space_repo
        self.completion_service = completion_service
        self.file_repo = file_repo
        self.template_asset_repo = template_asset_repo
        self.encryption_service = encryption_service
        self.max_inline_text_bytes = resolved_config.max_inline_text_bytes
        self.audit_service = audit_service
        self.references_service = references_service
        self.transcriber = transcriber
        self.variable_resolver = FlowVariableResolver()
        self.http_request_timeout_seconds = resolved_config.http_request_timeout_seconds
        self.http_max_timeout_seconds = resolved_config.http_max_timeout_seconds
        self.http_allow_private_networks = resolved_config.http_allow_private_networks
        self.http_runtime = FlowHttpRuntimeHelper(
            variable_resolver=self.variable_resolver,
            request_timeout_seconds=self.http_request_timeout_seconds,
            max_timeout_seconds=self.http_max_timeout_seconds,
            allow_private_networks=self.http_allow_private_networks,
        )
        self.runtime_policy = resolved_config.runtime_policy
        self.mapped_execution_policy = resolved_config.mapped_execution_policy
        self._step_deadline_seconds = resolved_config.step_deadline_seconds
        self.rag_retrieval_timeout_seconds = (
            resolved_config.rag_retrieval_timeout_seconds
        )
        self.document_render_service: DocumentRenderService = (
            default_document_render_service(
                limits=resolved_config.document_render_limits
            )
        )
        self.rag_max_reference_sources = resolved_config.rag_max_reference_sources
        self.rag_max_chunks_per_source = resolved_config.rag_max_chunks_per_source
        self.max_audio_files = resolved_config.max_audio_files
        self.max_generic_files = resolved_config.max_generic_files

    async def execute(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        run_revision: int,
        celery_task_id: str | None,
        retry_count: int,
    ) -> dict[str, object]:
        can_run = await self.flow_run_repo.mark_running_if_claimable(
            run_id=run_id,
            tenant_id=tenant_id,
            expected_revision=run_revision,
        )
        await self._commit()
        if not can_run:
            latest = await self.flow_run_repo.get(
                run_id=run_id, tenant_id=tenant_id, flow_id=flow_id
            )
            return {"status": "skipped", "reason": f"run_{latest.status.value}"}

        return await self.execute_claimed(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            celery_task_id=celery_task_id,
            retry_count=retry_count,
        )

    async def execute_claimed(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        celery_task_id: str | None,
        retry_count: int,
    ) -> dict[str, Any]:
        logger.info(
            "flow_executor.start run_id=%s flow_id=%s tenant_id=%s celery_retry_count=%d",
            run_id,
            flow_id,
            tenant_id,
            retry_count,
        )
        run = await self.flow_run_repo.get(
            run_id=run_id, tenant_id=tenant_id, flow_id=flow_id
        )
        if run.status != FlowRunStatus.RUNNING:
            logger.info(
                "flow_executor.skip run_id=%s reason=run_not_claimed status=%s",
                run_id,
                run.status,
            )
            return {"status": "skipped", "reason": f"run_{run.status.value}"}

        if not await self._flow_is_active(flow_id=flow_id, tenant_id=tenant_id):
            reason = "Flow was deleted before execution started."
            await self._terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.CANCELLED,
                source=FlowRunLifecycleSource.FLOW_DELETED,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.FLOW_DELETED,
                    code=FlowApiErrorCode.FLOW_DELETED,
                    message=reason,
                ),
            )
            await self._commit()
            return {
                "status": "cancelled",
                "reason": FlowApiErrorCode.FLOW_DELETED.value,
            }

        version = await self.flow_version_repo.get(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=tenant_id,
        )
        try:
            published_definition = parse_verified_published_definition(
                version.definition_json,
                expected_checksum=version.definition_checksum,
                flow_version=version.version,
            )
            steps = published_definition.runtime_steps()
        except PublishedDefinitionChecksumMismatchError as exc:
            await self._terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=FlowRunLifecycleSource.DEFINITION_CHECKSUM_MISMATCH,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.DEFINITION_CHECKSUM_MISMATCH,
                    code=FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH,
                    message=str(exc),
                ),
            )
            await self._commit()
            return {
                "status": "failed",
                "error": FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH.value,
            }
        except BadRequestException as exc:
            source = FlowRunLifecycleSource.INVALID_FLOW_DEFINITION
            await self._terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=source,
                error=(
                    run_error := self._run_error_from_bad_request(
                        exc,
                        source=source,
                        default_code=FlowApiErrorCode.DEFINITION_INVALID,
                    )
                ),
            )
            await self._commit()
            return {
                "status": "failed",
                "error": run_error.code.value,
            }
        except FlowRuntimeInvariantError as exc:
            source = FlowRunLifecycleSource.INVALID_FLOW_DEFINITION
            await self._terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=source,
                error=FlowRunError.from_source(
                    source,
                    code=FlowApiErrorCode.DEFINITION_NO_EXECUTABLE_STEPS,
                    message=str(exc),
                ),
            )
            await self._commit()
            return {
                "status": "failed",
                "error": FlowApiErrorCode.DEFINITION_NO_EXECUTABLE_STEPS.value,
            }
        if not steps:
            await self._terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
                    code=FlowApiErrorCode.DEFINITION_NO_EXECUTABLE_STEPS,
                    message="Published flow definition has no executable steps.",
                ),
            )
            await self._commit()
            return {
                "status": "failed",
                "error": FlowApiErrorCode.DEFINITION_NO_EXECUTABLE_STEPS.value,
            }
        version_metadata = version.definition_json.get("metadata_json")

        persisted_results = await self.flow_run_repo.list_step_results(
            run_id=run_id, tenant_id=tenant_id
        )
        state = build_run_execution_state(
            steps=steps, persisted_results=persisted_results
        )
        try:
            await self._validate_assistant_snapshots(
                steps=steps,
                state=state,
                run_id=run_id,
                require_snapshots=self._requires_assistant_snapshots(
                    version.definition_json
                ),
            )
        except BadRequestException as exc:
            source = FlowRunLifecycleSource.ASSISTANT_SNAPSHOT_DRIFT
            run_error = self._run_error_from_bad_request(
                exc,
                source=source,
                default_code=FlowApiErrorCode.ASSISTANT_SNAPSHOT_DRIFT,
            )
            await self._terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=source,
                error=run_error,
            )
            await self._commit()
            return {
                "status": "failed",
                "error": run_error.code.value,
            }

        try:
            active_rerun_operation = (
                await self.flow_run_rerun_repo.get_active_rerun_operation(
                    run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                )
            )
        except FlowRunRerunMultipleActiveOperationsError:
            return await self._handle_multiple_active_rerun_operations(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
            )
        active_rerun_steps_by_id = self._active_rerun_steps_by_id(
            active_rerun_operation
        )

        logger.info(
            "flow_executor.steps_parsed run_id=%s step_count=%d", run_id, len(steps)
        )
        step_output_levels: dict[int, int | None] = {}
        for step in sorted(steps, key=lambda item: item.step_order):
            step_output_levels[
                step.step_order
            ] = await self._validate_runtime_step_security(
                step=step,
                state=state,
                prior_output_levels_by_order=step_output_levels,
            )
            latest_run = await self.flow_run_repo.get(
                run_id=run_id, tenant_id=tenant_id, flow_id=flow_id
            )
            flow_active = await self._flow_is_active(
                flow_id=flow_id, tenant_id=tenant_id
            )
            preclaim_decision = build_step_gate_decision(
                latest_run_status=latest_run.status,
                flow_active=flow_active,
                claim_resolution=None,
                step_id=step.step_id,
            )
            if preclaim_decision.action == "return":
                return preclaim_decision.result or {
                    "status": "skipped",
                    "reason": "unknown",
                }
            if preclaim_decision.action == "cancel_flow_deleted":
                await self._terminalize_run(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    target_status=FlowRunStatus.CANCELLED,
                    source=FlowRunLifecycleSource.FLOW_DELETED,
                    error=FlowRunError.from_source(
                        FlowRunLifecycleSource.FLOW_DELETED,
                        code=FlowApiErrorCode.FLOW_DELETED,
                        message=preclaim_decision.run_error_message
                        or "Flow was deleted during execution.",
                    ),
                )
                await self._commit()
                return preclaim_decision.result or {
                    "status": "cancelled",
                    "reason": FlowApiErrorCode.FLOW_DELETED.value,
                }

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
                    return postclaim_decision.result or {
                        "status": "skipped",
                        "reason": "unknown",
                    }
                if postclaim_decision.action == "fail_step_missing":
                    await self._terminalize_run(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        target_status=FlowRunStatus.FAILED,
                        source=FlowRunLifecycleSource.STEP_MISSING,
                        error=FlowRunError.from_source(
                            FlowRunLifecycleSource.STEP_MISSING,
                            code=FlowApiErrorCode.STEP_MISSING,
                            message=postclaim_decision.run_error_message
                            or f"Missing step result for step {step.step_id}",
                        ),
                    )
                    await self._commit()
                    return postclaim_decision.result or {
                        "status": "failed",
                        "error": FlowApiErrorCode.STEP_MISSING.value,
                    }
                if (
                    postclaim_decision.action == "append_completed"
                    and postclaim_decision.completed_result is not None
                ):
                    state.append_completed(postclaim_decision.completed_result)
                    continue
                if postclaim_decision.action == "continue":
                    continue

            claimed_result = cast(FlowStepResult, claimed)
            try:
                started_attempt = await self._start_step_attempt(
                    run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step=step,
                    celery_task_id=celery_task_id,
                    active_rerun_operation=active_rerun_operation,
                    active_rerun_invalidated_step=active_rerun_steps_by_id.get(
                        step.step_id
                    ),
                )
                await self._commit()
                # A zero-model step can cross this commit before an external test
                # can stop it; exact test mode and run identity keep the exit inert.
                if get_settings().testing and os.environ.get(
                    _PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV
                ) == str(run_id):
                    os._exit(_PROCESS_TEST_CRASH_EXIT_CODE)
            except FlowRunRerunAttemptLineageConflictError:
                return await self._handle_attempt_start_failure(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    step=step,
                    claimed=claimed_result,
                    error_code=FlowApiErrorCode.RUN_RERUN_ATTEMPT_LINEAGE_CONFLICT_INVARIANT,
                    error_message=_RERUN_ATTEMPT_LINEAGE_CONFLICT_RUN_ERROR_MESSAGE,
                )
            except Exception:
                return await self._handle_attempt_start_failure(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    step=step,
                    claimed=claimed_result,
                )
            attempt_no = started_attempt.attempt_no

            logger.info(
                "flow_executor.step_start run_id=%s step_order=%d step_id=%s input_type=%s output_type=%s",
                run_id,
                step.step_order,
                step.step_id,
                step.input_type,
                step.output_type,
            )
            try:
                execution_result = await self._execute_step(
                    step=step,
                    run=latest_run,
                    state=state,
                    version_metadata=version_metadata,
                    attempt_no=attempt_no,
                )
                output = execution_result.output
            except FlowStepCancelledError:
                return await self._handle_cancelled_step(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    step=step,
                    attempt_no=attempt_no,
                    state=state,
                )
            except TypedIOValidationException as typed_exc:
                contract_diag: dict[str, Any] | None = None
                failed_input_payload = getattr(typed_exc, "input_payload_json", None)
                resolved_input_source = step.input_source
                if isinstance(failed_input_payload, dict):
                    failed_input_payload_dict = cast(
                        dict[str, Any], failed_input_payload
                    )
                    raw_contract_diag = failed_input_payload_dict.get(
                        "contract_validation"
                    )
                    contract_diag = (
                        cast(dict[str, Any], raw_contract_diag)
                        if isinstance(raw_contract_diag, dict)
                        else None
                    )
                    payload_source = failed_input_payload_dict.get("input_source")
                    if isinstance(payload_source, str) and payload_source:
                        resolved_input_source = payload_source
                    failed_input_payload = failed_input_payload_dict
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
                    contract_diag.get("schema_type_hint")
                    if isinstance(contract_diag, dict)
                    else None,
                    contract_diag.get("parse_attempted")
                    if isinstance(contract_diag, dict)
                    else None,
                    contract_diag.get("parse_succeeded")
                    if isinstance(contract_diag, dict)
                    else None,
                    contract_diag.get("candidate_type")
                    if isinstance(contract_diag, dict)
                    else None,
                    str(typed_exc),
                )
                return await self._handle_typed_step_failure(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    step=step,
                    attempt_no=attempt_no,
                    claimed=claimed_result,
                    typed_exc=typed_exc,
                    failed_input_payload=cast(
                        dict[str, Any] | None, failed_input_payload
                    ),
                    state=state,
                )
            except Exception as exc:
                logger.exception(
                    "flow_executor.step_failed run_id=%s step_order=%d error=%s",
                    run_id,
                    step.step_order,
                    str(exc),
                )
                return await self._handle_generic_step_failure(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    step=step,
                    attempt_no=attempt_no,
                    claimed=claimed_result,
                    state=state,
                    exc=exc,
                )

            latest_run = await self.flow_run_repo.get(
                run_id=run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )

            success_plan = build_step_success_plan(
                claimed=claimed_result,
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step=step,
                result=execution_result,
                output_payload_json=build_output_payload(output),
                execution_hash=execution_hash(
                    run_id=run_id,
                    step_id=step.step_id,
                    prompt=output.effective_prompt,
                    model_parameters=output.model_parameters_json,
                ),
            )
            step_result = success_plan.step_result
            persisted_step_result = await self._persist_successful_step(
                run_id=run_id,
                tenant_id=tenant_id,
                step=step,
                output=output,
                step_result=step_result,
                attempt_no=attempt_no,
                attempt_start=_attempt_start_for_step(state=state, step=step),
                commit=not success_plan.delivery_intents,
            )
            if persisted_step_result is None:
                return await self._return_after_terminalized_step_write(
                    run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                )
            step_result = persisted_step_result

            state.append_completed(step_result)

            review_policy = step.review_policy
            if review_policy is not None:
                return await self._open_review_checkpoint_for_completed_step(
                    run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    steps=steps,
                    step=step,
                    review_policy=review_policy,
                    attempt_no=attempt_no,
                )

            if success_plan.delivery_intents:
                for delivery_intent in success_plan.delivery_intents:
                    await self.webhook_delivery_repo.insert_pending_delivery(
                        flow_id=flow_id,
                        tenant_id=tenant_id,
                        intent=delivery_intent,
                    )
                await self._commit()
                return {"status": FlowRunStatus.RUNNING.value}

        results = await self.flow_run_repo.list_step_results(
            run_id=run_id, tenant_id=tenant_id
        )
        finalization = await finalize_run_from_current_results(
            run_id=run_id,
            tenant_id=tenant_id,
            results=results,
            terminalizer=self.flow_run_terminalizer,
            principal=self.principal,
        )
        await self._commit()
        return finalization.payload

    @staticmethod
    def _active_rerun_steps_by_id(
        operation: FlowRunActiveRerunOperation | None,
    ) -> dict[UUID, FlowRunRerunInvalidatedStep]:
        if operation is None:
            return {}
        return {step.step_id: step for step in operation.invalidated_steps}

    async def _start_step_attempt(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step: RuntimeStep,
        celery_task_id: str | None,
        active_rerun_operation: FlowRunActiveRerunOperation | None,
        active_rerun_invalidated_step: FlowRunRerunInvalidatedStep | None,
    ) -> FlowStepAttempt:
        attempt_no = await self._resolve_attempt_no(
            run_id=run_id,
            tenant_id=tenant_id,
            step=step,
            active_rerun_operation=active_rerun_operation,
            active_rerun_invalidated_step=active_rerun_invalidated_step,
        )
        started_attempt = await self.flow_run_repo.create_or_get_attempt_started(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            step_id=step.step_id,
            step_order=step.step_order,
            attempt_no=attempt_no,
            celery_task_id=celery_task_id,
            rerun_operation_id=(
                active_rerun_operation.operation.id
                if active_rerun_invalidated_step is not None
                and active_rerun_operation is not None
                else None
            ),
            predecessor_attempt_id=(
                active_rerun_invalidated_step.prior_attempt_id
                if active_rerun_invalidated_step is not None
                else None
            ),
        )
        if active_rerun_invalidated_step is not None:
            if active_rerun_operation is None:
                raise RuntimeError("Rerun step context requires an active operation.")
            if not (
                active_rerun_invalidated_step.role == FlowRunRerunInvalidationRole.ROOT
                and active_rerun_operation.operation.root_step_input_override_requested
            ):
                await self.flow_run_repo.copy_step_input_files_from_predecessor_attempt(
                    run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step_id=step.step_id,
                    step_order=step.step_order,
                    predecessor_attempt_id=(
                        active_rerun_invalidated_step.prior_attempt_id
                    ),
                    target_attempt_no=started_attempt.attempt_no,
                )
            await self.flow_run_rerun_repo.link_rerun_invalidated_step_attempt(
                operation_id=active_rerun_operation.operation.id,
                tenant_id=tenant_id,
                step_id=step.step_id,
                new_attempt_no=started_attempt.attempt_no,
                new_attempt_id=started_attempt.id,
            )
            if active_rerun_invalidated_step.role == FlowRunRerunInvalidationRole.ROOT:
                await self.flow_run_rerun_repo.mark_rerun_operation_running(
                    operation_id=active_rerun_operation.operation.id,
                    tenant_id=tenant_id,
                    root_attempt_id=started_attempt.id,
                )
        return started_attempt

    async def _resolve_attempt_no(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step: RuntimeStep,
        active_rerun_operation: FlowRunActiveRerunOperation | None,
        active_rerun_invalidated_step: FlowRunRerunInvalidatedStep | None,
    ) -> int:
        if (
            active_rerun_operation is not None
            and active_rerun_invalidated_step is not None
            and active_rerun_invalidated_step.role == FlowRunRerunInvalidationRole.ROOT
        ):
            return active_rerun_operation.operation.root_attempt_no
        return await self.flow_run_repo.allocate_next_attempt_no(
            tenant_id=tenant_id,
            flow_run_id=run_id,
            step_id=step.step_id,
        )

    async def _execute_step(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState | None = None,
        version_metadata: dict[str, Any] | None = None,
        attempt_no: int,
    ) -> StepExecutionResult:
        if state is None:
            state = RunExecutionState(
                completed_by_order={},
                prior_results=[],
                assistant_cache={},
                json_mode_supported={},
                file_cache={},
            )

        logger.info(
            "flow_executor.execute_step run_id=%s step_order=%d input_type=%s output_type=%s",
            run.id,
            step.step_order,
            step.input_type,
            step.output_type,
        )
        logger.debug(
            "flow_executor.resolving_input run_id=%s step_order=%d",
            run.id,
            step.step_order,
        )

        handler = self._build_step_handler(resolve_handler_mode(step.output_mode))
        with trace_flow_step(
            run_id=run.id,
            run_trace_id=run.trace_id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_id=step.step_id,
            step_order=step.step_order,
            attempt_no=attempt_no,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        ) as step_span:
            result = await handler.execute(
                step=step,
                run=run,
                state=state,
                version_metadata=version_metadata,
                attempt_no=attempt_no,
            )
            step_span.set_result(status="completed")
            return result

    def _build_step_handler(self, mode: FlowOutputMode) -> StepHandler:
        match mode:
            case FlowOutputMode.PASS_THROUGH:
                return PassThroughStepHandler(
                    prepare_assistant_step=self._prepare_assistant_step,
                    preview_assistant_step=self._preview_assistant_step,
                    list_step_input_file_ids=self._list_step_input_file_ids,
                    mapped_execution_policy=self.mapped_execution_policy,
                )
            case FlowOutputMode.COMPOSE_TEXT:
                return ComposeTextStepHandler(
                    prepare_assistant_step=self._prepare_assistant_step
                )
            case FlowOutputMode.HTTP_POST:
                return HttpPostStepHandler(
                    completion_handler=PassThroughStepHandler(
                        prepare_assistant_step=self._prepare_assistant_step,
                        preview_assistant_step=self._preview_assistant_step,
                        list_step_input_file_ids=self._list_step_input_file_ids,
                        mapped_execution_policy=self.mapped_execution_policy,
                    )
                )
            case FlowOutputMode.TRANSCRIBE_ONLY:
                return TranscribeOnlyStepHandler(
                    prepare_assistant_step=self._prepare_assistant_step
                )
            case FlowOutputMode.TEMPLATE_FILL:
                return TemplateFillStepHandler(deps=self._template_fill_runtime_deps())
            case FlowOutputMode.RENDER_VERBATIM:
                return RenderVerbatimStepHandler(
                    prepare_assistant_step=self._prepare_assistant_step
                )
        assert_never(mode)

    def _template_fill_runtime_deps(self) -> TemplateFillRuntimeDeps:
        return TemplateFillRuntimeDeps(
            variable_resolver=self.variable_resolver,
            file_repo=self.file_repo,
            template_asset_repo=self.template_asset_repo,
            apply_output_cap=self._apply_output_cap_positional,
            principal=self.principal,
            logger=logger,
        )

    def _build_step_execution_runtime_deps(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        attempt_no: int,
    ) -> StepExecutionRuntimeDeps:
        try:
            llm_timeout_seconds = self._step_deadline_seconds(step)
        except BadRequestException as exc:
            raise TypedIOValidationException(
                str(exc),
                code=exc.code,
                context=exc.context,
            ) from exc

        return StepExecutionRuntimeDeps(
            variable_resolver=self.variable_resolver,
            completion_service=self.completion_service,
            load_assistant=self._load_assistant,
            resolve_step_input=self._resolve_step_input,
            retrieve_rag_chunks=self._retrieve_rag_chunks,
            process_typed_output=self._process_typed_output,
            apply_output_cap=self._apply_output_cap,
            max_inline_text_bytes=self.max_inline_text_bytes,
            logger=logger,
            llm_request_timeout_seconds=llm_timeout_seconds,
            rag_retrieval_timeout_seconds=self.rag_retrieval_timeout_seconds,
            run_cancelled=self._run_is_cancelled,
            build_provider_call_observer=lambda mapped_call: FlowProviderCallRecorder(
                run_id=run.id,
                step_id=step.step_id,
                attempt_no=attempt_no,
                tenant_id=run.tenant_id,
                mapped_call=mapped_call,
            ),
        )

    async def _prepare_assistant_step(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: FlowPersistedJsonObject | None,
        attempt_no: int,
        requested_file_ids_override: Sequence[UUID] | None = None,
        step_input_override: StepInputValue | None = None,
    ) -> PreparedAssistantStep:
        execution_deps = self._build_step_execution_runtime_deps(
            step=step,
            run=run,
            attempt_no=attempt_no,
        )
        if requested_file_ids_override is None:
            requested_file_ids = await self._list_step_input_file_ids(
                step=step,
                run=run,
                attempt_no=attempt_no,
            )
        else:
            requested_file_ids = list(requested_file_ids_override)
        prepared = await prepare_step_execution(
            step=step,
            run=run,
            state=state,
            version_metadata=version_metadata,
            requested_file_ids=requested_file_ids,
            deps=execution_deps,
            step_input_override=step_input_override,
        )
        requested_model = _requested_model_from_assistant(prepared.assistant)
        provider = _provider_from_assistant(prepared.assistant)
        resolved_timeout_seconds = int(execution_deps.llm_request_timeout_seconds)
        attempt_start = AttemptStartProvenance(
            requested_model=requested_model,
            provider=provider,
            deadline_at=datetime.now(timezone.utc)
            + timedelta(seconds=resolved_timeout_seconds),
            resolved_timeout_seconds=resolved_timeout_seconds,
            effective_prompt_length=len(prepared.effective_prompt),
            input_text_length=len(prepared.step_input.text),
            input_tokens_estimate=count_tokens(prepared.step_input.text),
            model_parameter_snapshot=_model_parameter_snapshot(prepared.assistant),
            mapped_admission=state.mapped_admission_by_step.get(step.step_id),
        )
        state.attempt_start_by_step[step.step_id] = attempt_start
        contract_validation = prepared.contract_validation or {}
        logger.info(
            "flow_executor.step_prepared run_id=%s step_order=%d requested_model=%s "
            "provider=%s input_type=%s input_source=%s output_type=%s "
            "used_question_binding=%s input_text_len=%d source_text_len=%d "
            "effective_prompt_len=%d contract_parse_attempted=%s "
            "contract_parse_succeeded=%s",
            run.id,
            step.step_order,
            requested_model,
            provider,
            step.input_type,
            prepared.step_input.input_source,
            step.output_type,
            prepared.step_input.used_question_binding,
            len(prepared.step_input.text),
            len(prepared.step_input.source_text),
            len(prepared.effective_prompt),
            contract_validation.get("parse_attempted"),
            contract_validation.get("parse_succeeded"),
        )
        await self.flow_run_repo.record_attempt_start_provenance(
            run_id=run.id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=run.tenant_id,
            requested_model=requested_model,
            provider=provider,
            attempt_start=attempt_start,
        )
        await self._commit()
        return PreparedAssistantStep(prepared=prepared, deps=execution_deps)

    async def _preview_assistant_step(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: FlowPersistedJsonObject | None,
        attempt_no: int,
        requested_file_ids_override: Sequence[UUID] | None = None,
        step_input_override: StepInputValue | None = None,
    ) -> PreparedAssistantStep:
        """Prepare mapped input without recording attempt-start or committing."""
        execution_deps = self._build_step_execution_runtime_deps(
            step=step,
            run=run,
            attempt_no=attempt_no,
        )
        requested_file_ids = (
            await self._list_step_input_file_ids(
                step=step,
                run=run,
                attempt_no=attempt_no,
            )
            if requested_file_ids_override is None
            else list(requested_file_ids_override)
        )
        prepared = await prepare_step_execution(
            step=step,
            run=run,
            state=state,
            version_metadata=version_metadata,
            requested_file_ids=requested_file_ids,
            deps=execution_deps,
            step_input_override=step_input_override,
        )
        return PreparedAssistantStep(prepared=prepared, deps=execution_deps)

    async def _list_step_input_file_ids(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        attempt_no: int,
    ) -> list[UUID]:
        if not build_runtime_input_config(step.input_config).enabled:
            return []
        return await self.flow_run_repo.list_step_input_file_ids(
            run_id=run.id,
            tenant_id=run.tenant_id,
            step_id=step.step_id,
            attempt_no=attempt_no,
        )

    async def _retrieve_rag_chunks(
        self,
        *,
        assistant: RuntimeAssistantProtocol,
        question: str,
        run_id: UUID,
        step_order: int,
    ) -> tuple[list[InfoBlobChunkInDBWithScore], dict[str, Any], list[StepDiagnostic]]:
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
        return await self.flow_repo.is_active(flow_id=flow_id, tenant_id=tenant_id)

    async def _run_is_cancelled(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> bool:
        run = await self.flow_run_repo.get(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
        )
        return run.status == FlowRunStatus.CANCELLED

    async def _handle_multiple_active_rerun_operations(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        await self._rollback()
        logger.critical(
            "flow_executor.rerun_multiple_active_operations_terminalized_failed "
            "run_id=%s code=%s",
            run_id,
            FlowApiErrorCode.RUN_RERUN_MULTIPLE_ACTIVE_OPERATIONS_INVARIANT.value,
            exc_info=True,
        )
        await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.EXECUTOR_FAILED,
                code=FlowApiErrorCode.RUN_RERUN_MULTIPLE_ACTIVE_OPERATIONS_INVARIANT,
                message=_RERUN_MULTIPLE_ACTIVE_OPERATIONS_RUN_ERROR_MESSAGE,
            ),
        )
        await self._commit()
        return await self._return_after_terminalized_step_write(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
        )

    async def _return_after_terminalized_step_write(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        run = await self.flow_run_repo.get(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
        )
        if run.status == FlowRunStatus.CANCELLED:
            return {"status": "skipped", "reason": "run_cancelled"}
        if run.status == FlowRunStatus.FAILED:
            error_message = (
                run.error.message if run.error is not None else "flow_run_failed"
            )
            return {"status": "failed", "error": error_message}
        raise RuntimeError(
            "Step result write was skipped, but the flow run is not terminal."
        )

    async def _handle_attempt_start_failure(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step: RuntimeStep,
        claimed: FlowStepResult,
        error_code: FlowApiErrorCode | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        run_error_code = error_code or FlowApiErrorCode.STEP_ATTEMPT_START_FAILED
        logger.exception(
            "flow_executor.step_attempt_start_failed run_id=%s step_order=%d step_id=%s code=%s",
            run_id,
            step.step_order,
            step.step_id,
            run_error_code.value,
        )
        failure_plan = build_generic_failure_plan(
            claimed=claimed,
            public_error=f"Flow step {step.step_order} execution failed.",
        )
        run_error_message = error_message or failure_plan.run_error_message
        await self._rollback()
        await self.flow_run_repo.save_step_result(
            run_id,
            failure_plan.failed_result,
            tenant_id=tenant_id,
            attempt_no=None,
        )
        await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.EXECUTOR_FAILED,
                code=run_error_code,
                message=run_error_message,
                step_order=step.step_order,
            ),
        )
        await self._commit()
        return failure_plan.return_result

    async def _handle_cancelled_step(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step: RuntimeStep,
        attempt_no: int,
        state: RunExecutionState | None,
    ) -> dict[str, Any]:
        await self._rollback()
        attempt_start = _attempt_start_for_step(state=state, step=step)
        requested_model, provider = (
            (
                attempt_start.requested_model,
                attempt_start.provider,
            )
            if attempt_start is not None
            else _pre_attempt_start_model_from_state_cache(state=state, step=step)
        )
        await self.flow_run_repo.finish_attempt(
            run_id=run_id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=tenant_id,
            status=FlowStepAttemptStatus.CANCELLED,
            error_code=FlowApiErrorCode.RUN_CANCELLED.value,
            error_message="Run was cancelled during step execution.",
            requested_model=requested_model,
            provider=provider,
            provenance_json=_build_incomplete_attempt_provenance(
                state=state,
                step=step,
            ),
        )
        await self._commit()
        return {"status": "skipped", "reason": "run_cancelled"}

    async def _handle_typed_step_failure(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step: RuntimeStep,
        attempt_no: int,
        claimed: FlowStepResult,
        typed_exc: TypedIOValidationException,
        failed_input_payload: dict[str, Any] | None,
        state: RunExecutionState | None = None,
    ) -> dict[str, Any]:
        failed_prompt = getattr(typed_exc, "effective_prompt", None)
        error_code = _typed_io_failure_code(typed_exc.code)
        error_message = _with_provider_work_disclosure(str(typed_exc), step=step)
        run_error_message = _with_provider_work_disclosure(
            build_typed_failure_run_error_message(
                step_order=step.step_order,
                error_code=error_code,
                error_message=str(typed_exc),
                contract_validation=getattr(typed_exc, "contract_validation", None),
            ),
            step=step,
        )
        failure_plan = build_typed_failure_plan(
            claimed=claimed,
            error_code=error_code,
            error_message=error_message,
            input_payload_json=failed_input_payload,
            effective_prompt=failed_prompt if isinstance(failed_prompt, str) else None,
            run_error_message=run_error_message,
        )
        await self._rollback()
        requested_model = getattr(typed_exc, "requested_model", None)
        provider = getattr(typed_exc, "provider", None)
        if requested_model is None or provider is None:
            attempt_start = _attempt_start_for_step(state=state, step=step)
            state_model, state_provider = (
                (
                    attempt_start.requested_model,
                    attempt_start.provider,
                )
                if attempt_start is not None
                else _pre_attempt_start_model_from_state_cache(state=state, step=step)
            )
            if requested_model is None:
                requested_model = state_model
            if provider is None:
                provider = state_provider
        await self.flow_run_repo.finish_attempt(
            run_id=run_id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=tenant_id,
            status=failure_plan.attempt_status,
            error_code=failure_plan.error_code.value,
            error_message=failure_plan.error_message,
            requested_model=requested_model
            if isinstance(requested_model, str)
            else None,
            provider=provider if isinstance(provider, str) else None,
            provenance_json=_build_incomplete_attempt_provenance(
                state=state,
                step=step,
            ),
            input_payload_json=failure_plan.failed_result.input_payload_json,
            output_payload_json=failure_plan.failed_result.output_payload_json,
        )
        await self.flow_run_repo.save_step_result(
            run_id,
            failure_plan.failed_result,
            tenant_id=tenant_id,
            attempt_no=attempt_no,
        )
        await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.EXECUTOR_FAILED,
                code=failure_plan.error_code,
                message=failure_plan.run_error_message,
                step_order=step.step_order,
            ),
        )
        await self._commit()
        return failure_plan.return_result

    async def _handle_generic_step_failure(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step: RuntimeStep,
        attempt_no: int,
        claimed: FlowStepResult,
        state: RunExecutionState | None = None,
        exc: Exception | None = None,
    ) -> dict[str, Any]:
        evidence_persistence_error = (
            exc if isinstance(exc, ProviderCallEvidencePersistenceError) else None
        )
        late_capability_rejection = (
            isinstance(exc, ProviderCapabilityRejectedException)
            and not exc.retry_without_capability_safe
        )
        if evidence_persistence_error is not None:
            if evidence_persistence_error.facts.call_id is None:
                public_error = (
                    f"Flow step {step.step_order} stopped before provider I/O because "
                    "request evidence could not be persisted."
                )
            else:
                public_error = (
                    f"Flow step {step.step_order} failed after provider work because "
                    "provider-call evidence could not be persisted; the call was not "
                    "repeated."
                )
        elif isinstance(exc, ProviderRejectedRequestException) and not (
            late_capability_rejection
        ):
            public_error = (
                f"Flow step {step.step_order} execution failed because the provider "
                "rejected the request; the runtime did not repeat it."
            )
        else:
            public_error = _with_provider_work_disclosure(
                f"Flow step {step.step_order} execution failed.",
                step=step,
            )
        failure_plan = build_generic_failure_plan(
            claimed=claimed,
            public_error=public_error,
            error_code=(
                FlowApiErrorCode.PROVIDER_CALL_EVIDENCE_PERSISTENCE_FAILED
                if evidence_persistence_error is not None
                else FlowApiErrorCode.STEP_EXECUTION_FAILED
            ),
        )
        await self._rollback()
        attempt_start = _attempt_start_for_step(state=state, step=step)
        requested_model, provider = (
            (
                attempt_start.requested_model,
                attempt_start.provider,
            )
            if attempt_start is not None
            else _pre_attempt_start_model_from_state_cache(state=state, step=step)
        )
        await self.flow_run_repo.finish_attempt(
            run_id=run_id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=tenant_id,
            status=failure_plan.attempt_status,
            error_code=failure_plan.error_code.value,
            error_message=failure_plan.error_message,
            requested_model=requested_model,
            provider=provider,
            provenance_json=_build_incomplete_attempt_provenance(
                state=state,
                step=step,
            ),
            input_payload_json=failure_plan.failed_result.input_payload_json,
            output_payload_json=failure_plan.failed_result.output_payload_json,
        )
        await self.flow_run_repo.save_step_result(
            run_id,
            failure_plan.failed_result,
            tenant_id=tenant_id,
            attempt_no=attempt_no,
        )
        await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.EXECUTOR_FAILED,
                code=failure_plan.error_code,
                message=failure_plan.run_error_message,
                step_order=step.step_order,
                details=(
                    FlowRunErrorDetails(
                        provider_call_evidence_gap=evidence_persistence_error.facts
                    )
                    if evidence_persistence_error is not None
                    else None
                ),
            ),
        )
        await self._commit()
        return failure_plan.return_result

    async def _persist_successful_step(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step: RuntimeStep,
        output: StepExecutionOutput,
        step_result: FlowStepResult,
        attempt_no: int,
        attempt_start: AttemptStartProvenance | None,
        commit: bool = True,
    ) -> FlowStepResult | None:
        saved_result = await self.flow_run_repo.save_step_result(
            run_id,
            step_result,
            tenant_id=tenant_id,
            attempt_no=attempt_no,
            result_file_references=build_step_result_file_references(
                generated_file_ids=output.generated_file_ids,
                artifacts=output.artifacts,
            ),
        )
        if saved_result is None:
            await self._commit()
            return None
        logger.info(
            "flow_executor.step_completed run_id=%s step_order=%d",
            run_id,
            step.step_order,
        )
        await self.flow_run_repo.finish_attempt(
            run_id=run_id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
            requested_model=output.requested_model,
            response_model=output.response_model,
            provider=output.provider,
            finish_reason=output.finish_reason,
            provider_response_id=output.provider_response_id,
            num_tokens_input=output.num_tokens_input,
            num_tokens_output=output.num_tokens_output,
            provenance_json=_build_attempt_provenance(
                step=step,
                output=output,
                step_result=step_result,
                attempt_start=attempt_start,
            ),
            input_payload_json=saved_result.input_payload_json,
            output_payload_json=saved_result.output_payload_json,
        )
        if commit:
            await self._commit()
        return step_result

    async def _open_review_checkpoint_for_completed_step(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        steps: list[RuntimeStep],
        step: RuntimeStep,
        review_policy: FlowStepReviewPolicy,
        attempt_no: int,
    ) -> dict[str, Any]:
        try:
            opened = await self.flow_run_review_checkpoint_repo.open_review_checkpoint_for_completed_step(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=run_id,
                step_id=step.step_id,
                step_order=step.step_order,
                attempt_no=attempt_no,
                requester_principal=self.principal,
                next_step_ids=self._next_step_ids_after_reviewed_step(
                    steps=steps,
                    reviewed_step=step,
                ),
                step_label=step.user_description,
                review_mode=review_policy.mode,
                output_type=FlowOutputType(step.output_type),
                output_contract_json=step.output_contract,
                review_expires_after_seconds=review_policy.expires_after_seconds,
            )
        except FlowReviewCheckpointRunNotRunningError:
            await self._rollback()
            logger.info(
                "flow_executor.review_open_skipped_run_terminal "
                "run_id=%s step_order=%d step_id=%s",
                run_id,
                step.step_order,
                step.step_id,
            )
            return await self._return_after_terminalized_step_write(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
            )
        except FLOW_REVIEW_CHECKPOINT_OPEN_TERMINAL_INVARIANT_CLASSES as exc:
            return await self._handle_review_checkpoint_open_terminal_invariant(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step=step,
                exc=exc,
            )
        await self._commit()
        logger.info(
            "flow_executor.awaiting_review run_id=%s step_order=%d checkpoint_id=%s",
            run_id,
            step.step_order,
            opened.checkpoint.id,
        )
        return {"status": opened.run.status.value}

    async def _handle_review_checkpoint_open_terminal_invariant(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step: RuntimeStep,
        exc: FlowReviewCheckpointOpenTerminalInvariantFailure,
    ) -> dict[str, Any]:
        from eneo.flows.application.flow_run_review_checkpoint_service import (
            review_open_terminal_invariant_error,
        )

        error_code, error_message = review_open_terminal_invariant_error(exc)
        await self._rollback()
        if isinstance(exc, FlowReviewMultipleActiveCheckpointsError):
            logger.critical(
                "flow_executor.review_open_multiple_active_terminalized_failed "
                "run_id=%s step_order=%d step_id=%s code=%s",
                run_id,
                step.step_order,
                step.step_id,
                error_code.value,
                exc_info=True,
            )
        else:
            logger.exception(
                "flow_executor.review_open_terminalized_failed "
                "run_id=%s step_order=%d step_id=%s code=%s",
                run_id,
                step.step_order,
                step.step_id,
                error_code,
            )
        await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.EXECUTOR_FAILED,
                code=error_code,
                message=error_message,
                step_id=step.step_id,
                step_order=step.step_order,
            ),
        )
        await self._commit()
        return await self._return_after_terminalized_step_write(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
        )

    @staticmethod
    def _next_step_ids_after_reviewed_step(
        *,
        steps: list[RuntimeStep],
        reviewed_step: RuntimeStep,
    ) -> tuple[UUID, ...]:
        return tuple(
            step.step_id
            for step in sorted(steps, key=lambda item: item.step_order)
            if step.step_order > reviewed_step.step_order
        )

    async def _resolve_step_input(
        self,
        *,
        step: RuntimeStep,
        context: dict[str, Any],
        run: FlowRun,
        prior_results: list[FlowStepResult],
        state: RunExecutionState | None = None,
        version_metadata: dict[str, Any] | None = None,
        requested_file_ids: Sequence[UUID] = (),
    ) -> StepInputValue:
        deps = StepInputResolutionDeps(
            variable_resolver=self.variable_resolver,
            resolve_http_input_source_text=self._resolve_http_input_source_text,
            file_repo=self.file_repo,
            principal=self.principal,
            transcriber=self.transcriber,
            space_repo=self.space_repo,
            flow_run_repo=self.flow_run_repo,
            audit_service=self.audit_service,
            actor=self.runtime_actor,
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
            state=state,
            version_metadata=version_metadata,
            requested_file_ids=requested_file_ids,
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

    async def _load_assistant(
        self, assistant_id: UUID, state: RunExecutionState | None = None
    ) -> RuntimeAssistantProtocol:
        if state and assistant_id in state.assistant_cache:
            assistant = state.assistant_cache[assistant_id]
            self._reject_flow_mcp_assistant(assistant)
            return assistant
        space = await self._load_space_for_assistant(
            assistant_id=assistant_id, state=state
        )
        assistant = space.get_assistant(assistant_id=assistant_id)
        self._reject_flow_mcp_assistant(assistant)
        if state:
            state.assistant_cache[assistant_id] = assistant
        return assistant

    @staticmethod
    def _reject_flow_mcp_assistant(assistant: RuntimeAssistantProtocol) -> None:
        if assistant.mcp_servers:
            raise BadRequestException(
                "Flow MCP is unsupported. Remove MCP servers and tools from the step assistant before running the flow."
            )

    async def _load_space_for_assistant(
        self, *, assistant_id: UUID, state: RunExecutionState | None = None
    ) -> Space:
        if state and assistant_id in state.space_cache:
            return state.space_cache[assistant_id]

        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        if state:
            # Pin Space for this run pass; assistant snapshots are already pass-scoped.
            state.space_cache[assistant_id] = space
            if space.default_assistant is not None:
                state.space_cache[space.default_assistant.id] = space
            for assistant in space.assistants:
                state.space_cache[assistant.id] = space
        return space

    async def _validate_assistant_snapshots(
        self,
        *,
        steps: list[RuntimeStep],
        state: RunExecutionState,
        run_id: UUID,
        require_snapshots: bool = False,
    ) -> None:
        for step in steps:
            if step.assistant_snapshot is None:
                if require_snapshots:
                    raise BadRequestException(
                        f"Step {step.step_order}: assistant snapshot is missing from the published flow definition. Republish the flow before running it."
                    )
                continue

            validated_snapshot = validate_assistant_execution_snapshot(
                snapshot=step.assistant_snapshot,
                assistant_id=step.assistant_id,
            )
            current_assistant = await self._load_assistant(step.assistant_id, state)
            self._reject_flow_mcp_assistant(current_assistant)
            current_snapshot = build_assistant_execution_snapshot(
                assistant=current_assistant,
            )
            if current_snapshot is None:
                raise BadRequestException(
                    f"Step {step.step_order}: assistant snapshot could not be validated."
                )

            expected_hash = cast(str, validated_snapshot["execution_surface_hash"])
            current_hash = current_snapshot.get("execution_surface_hash")
            if expected_hash == current_hash:
                continue

            logger.warning(
                "flow_executor.assistant_snapshot_drift run_id=%s step_order=%d assistant_id=%s expected_hash=%s current_hash=%s",
                run_id,
                step.step_order,
                step.assistant_id,
                expected_hash,
                current_hash,
            )
            raise BadRequestException(
                f"Step {step.step_order}: assistant configuration changed after publish. Republish the flow before running it."
            )

    async def _validate_runtime_step_security(
        self,
        *,
        step: RuntimeStep,
        state: RunExecutionState,
        prior_output_levels_by_order: dict[int, int | None],
    ) -> int | None:
        space = await self._load_space_for_assistant(
            assistant_id=step.assistant_id, state=state
        )
        assistant = await self._load_assistant(step.assistant_id, state)
        evaluation = evaluate_step_security_classification(
            step_order=step.step_order,
            input_source=step.input_source,
            output_classification_override=step.output_classification_override,
            prior_output_levels_by_order=prior_output_levels_by_order,
            assistant=assistant,
            space=space,
        )
        return evaluation.effective_output_level

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
            actor=self.runtime_actor,
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

    async def _process_typed_output(
        self,
        *,
        full_text: str,
        step: RuntimeStep,
        run: FlowRun,
    ) -> TypedOutputProcessingResult:
        from eneo.flows.output_processing import (
            compile_validators,
            parse_json_output,
            validate_against_contract,
        )

        deps = OutputRuntimeDeps(
            file_repo=self.file_repo,
            principal=self.principal,
            compile_validators=compile_validators,
            parse_json_output=parse_json_output,
            validate_against_contract=validate_against_contract,
            render_document=self.document_render_service.render_document,
            render_structured_document=(
                self.document_render_service.render_structured_document
            ),
            document_render_limits=self.document_render_service.limits,
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

        owner_fields = FlowPrincipal.from_run(run).file_owner_fields()
        file_row = await self.file_repo.add(
            FileCreate.model_validate(
                {
                    "name": f"flow-{run.id}-step-{step.step_order}-output.txt",
                    "checksum": hashlib.sha256(encoded).hexdigest(),
                    "size": len(encoded),
                    "mimetype": "text/plain",
                    "file_type": FileType.TEXT,
                    "text": text,
                    **owner_fields,
                    "tenant_id": run.tenant_id,
                }
            )
        )
        return _utf8_prefix(text, max_bytes=self.max_inline_text_bytes), [file_row.id]

    async def _apply_output_cap_positional(
        self,
        text: str,
        run: FlowRun,
        step: RuntimeStep,
    ) -> tuple[str, list[UUID]]:
        return await self._apply_output_cap(text=text, run=run, step=step)

    @staticmethod
    def _requires_assistant_snapshots(definition_json: dict[str, Any]) -> bool:
        schema_version = definition_json.get("schema_version")
        return isinstance(schema_version, int) and schema_version >= 1

    @staticmethod
    def _run_error_from_bad_request(
        exc: BadRequestException,
        *,
        source: FlowRunLifecycleSource,
        default_code: FlowApiErrorCode,
    ) -> FlowRunError:
        context = exc.context
        step_order_value = context.get("step_order") if context is not None else None
        step_order = (
            step_order_value
            if isinstance(step_order_value, int)
            and not isinstance(step_order_value, bool)
            else None
        )
        return FlowRunError.from_source(
            source,
            code=_flow_api_error_code_or_default(
                exc.code,
                default_code=default_code,
            ),
            message=str(exc),
            step_order=step_order,
            details=FlowRunErrorDetails.from_bad_request_context(context),
        )

    async def _terminalize_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        source: FlowRunLifecycleSource,
        error: FlowRunError | None = None,
        output_payload_json: FlowPersistedJsonObject | None = None,
        cancelled_at: datetime | None = None,
    ) -> FlowRunTerminalizationResult:
        return await self.flow_run_terminalizer.terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=target_status,
            source=source,
            error=error,
            output_payload_json=output_payload_json,
            cancelled_at=cancelled_at,
            principal=self.principal,
        )

    async def _commit(self) -> None:
        await self.session.commit()

    async def _rollback(self) -> None:
        await self.session.rollback()
