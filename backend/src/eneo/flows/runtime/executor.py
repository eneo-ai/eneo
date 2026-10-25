from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any, Iterable, Sequence, assert_never, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant, AssistantOrigin
from eneo.audit.domain.outcome import Outcome
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.database import sessionmanager
from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_models import File, FileMetadata, FileType
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.flows.application.flow_run_terminalization import (
    FlowRunTerminalizationResult,
    FlowRunTerminalizer,
)
from eneo.flows.application.flow_webhook_delivery_policy import (
    flow_webhook_delivery_request,
    flow_webhook_delivery_request_timeout_seconds,
)
from eneo.flows.assistant_execution_snapshot import (
    AssistantExecutionSnapshotV2,
    validate_assistant_execution_snapshot,
)
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
)
from eneo.flows.domain.flow_run_exceptions import FlowStepAttemptClosed
from eneo.flows.domain.flow_step_attempt_input import (
    FlowStepAttemptCompletionConfiguration,
    FlowStepAttemptExecutionInput,
    FlowStepAttemptStart,
    FlowStepAttemptToolCallResult,
    FlowStepAttemptToolCallStart,
    parse_flow_step_attempt_input,
)
from eneo.flows.domain.flow_step_validation import require_completion_model_for_step
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    resolve_flow_mapped_execution_policy,
)
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.domain.review_checkpoint_exceptions import (
    FLOW_REVIEW_CHECKPOINT_OPEN_TERMINAL_INVARIANT_CLASSES,
    FlowReviewCheckpointOpenTerminalInvariantFailure,
    FlowReviewCheckpointRunNotRunningError,
    FlowReviewMultipleActiveCheckpointsError,
)
from eneo.flows.domain.review_edit_references import (
    REVIEWED_EDIT_READ_MAX_LOGICAL_BYTES,
    REVIEWED_EDIT_READ_MAX_ROWS,
    reviewed_result_attempts,
    reviewed_results,
)
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
    assistant_cache_key,
)
from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.flows.domain.step_output import (
    InlineTranscript,
    StepOutputValidationException,
    build_step_material_aliases,
    utf8_prefix,
)
from eneo.flows.domain.text_processing import SummarizationProvenance
from eneo.flows.domain.tool_facts import ToolFactsReadOnce, UnattendedToolFactsSource
from eneo.flows.domain.transcript_source import (
    TranscriptSourceReference,
    with_transcript_source_reference,
)
from eneo.flows.enums import (
    FlowInputSource,
    FlowOutputMode,
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowStepPhase,
    flow_output_mode_uses_completion_model,
)
from eneo.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FlowApiErrorCode,
    typed_io_failure_code,
)
from eneo.flows.flow_input_limits import FlowInputLimits
from eneo.flows.flow_review_policy import FlowStepReviewPolicy
from eneo.flows.flow_run_error import (
    FlowRunError,
    FlowRunErrorDetails,
    after_possible_tool_call,
    tool_call_possible,
)
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
    FlowResolvedInputEdgeGrouping,
    FlowResolvedInputEdges,
    group_resolved_input_edges,
)
from eneo.flows.flow_run_step_result_file import build_step_result_file_references
from eneo.flows.flow_runtime_policy import (
    STEP_TIMEOUT_TASK_BUFFER_SECONDS,
    FlowRuntimePolicy,
    default_flow_runtime_policy,
    resolve_step_timeout_seconds,
)
from eneo.flows.flow_security_classification import (
    ExternalSourceClassification,
    evaluate_step_security_classification,
    evidence_classification_level,
    read_tool_source_classification,
)
from eneo.flows.flow_template_asset_repo import FlowTemplateAssetRepository
from eneo.flows.http_transport import (
    credential_template_message,
    sent_step_http_configs,
    templated_step_credentials,
)
from eneo.flows.infrastructure.flow_provider_call_recorder import (
    FlowProviderCallRecorder,
    ProviderCallEvidencePersistenceError,
)
from eneo.flows.infrastructure.flow_provider_call_repo import FlowProviderCallRepository
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunExecutionOwner,
    FlowRunRepository,
)
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.infrastructure.flow_transcript_source_repo import (
    FlowTranscriptSourceRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.infrastructure.session_writes import TransactionWrites
from eneo.flows.published_definition import (
    PublishedDefinitionChecksumMismatchError,
    parse_verified_published_definition,
)
from eneo.flows.runtime import step_deadline as step_deadline_module
from eneo.flows.runtime.claim_resolution import resolve_step_claim
from eneo.flows.runtime.contract_check import check_contract_in_child
from eneo.flows.runtime.document_rendering import DocumentRenderService
from eneo.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
)
from eneo.flows.runtime.document_rendering.service import (
    default_document_render_service,
)
from eneo.flows.runtime.egress.policy import (
    FlowDestinationPolicy,
    FlowOutboundTraffic,
    Resolver,
)
from eneo.flows.runtime.egress.resolver import flow_name_resolver
from eneo.flows.runtime.execution_heartbeat import (
    FlowExecutionOwnershipLost,
    current_execution_ownership_lost,
    execution_heartbeats,
    execution_ownership_is_lost,
)
from eneo.flows.runtime.execution_state_builder import build_run_execution_state
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.flow_runtime_trace import trace_flow_step
from eneo.flows.runtime.generated_file_names import GeneratedFileNames
from eneo.flows.runtime.http_audit import (
    AuditedToolCall,
    HttpAuditDeps,
)
from eneo.flows.runtime.http_audit import (
    audit_http_outbound as audit_http_outbound_runtime,
)
from eneo.flows.runtime.http_orchestration import (
    FlowHttpOrchestrationDeps,
    FlowOutsideInputResolution,
)
from eneo.flows.runtime.http_orchestration import (
    resolve_http_input_source_text as resolve_http_input_source_text_orchestrated,
)
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.flows.runtime.output_runtime import (
    OutputRuntimeDeps,
    TypedOutputProcessingResult,
    save_generated_flow_file,
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
from eneo.flows.runtime.step_deadline import (
    StepDeadline,
    StepDeadlineExceeded,
    record_step_phase,
    require_step_budget,
    step_deadline_scope,
)
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import (
    FlowStepCancelledError,
    StepExecutionRuntimeDeps,
    build_output_payload,
    build_prepared_completion_call,
    execution_hash,
    prepare_step_execution,
)
from eneo.flows.runtime.step_failure_evidence import (
    attach_failure_evidence,
    failure_evidence,
    rejected_output_of,
)
from eneo.flows.runtime.step_handlers import resolve_handler_mode
from eneo.flows.runtime.step_handlers.base import PreparedAssistantStep, StepHandler
from eneo.flows.runtime.step_handlers.compose_text import ComposeTextStepHandler
from eneo.flows.runtime.step_handlers.copy_input import CopyInputStepHandler
from eneo.flows.runtime.step_handlers.http_post import HttpPostStepHandler
from eneo.flows.runtime.step_handlers.pass_through import PassThroughStepHandler
from eneo.flows.runtime.step_handlers.render_verbatim import RenderVerbatimStepHandler
from eneo.flows.runtime.step_handlers.speaker_mapping import (
    SpeakerMappingStepHandler,
)
from eneo.flows.runtime.step_handlers.template_fill import TemplateFillStepHandler
from eneo.flows.runtime.step_handlers.transcribe_only import TranscribeOnlyStepHandler
from eneo.flows.runtime.step_input_resolution import (
    StepInputResolutionDeps,
    admit_runtime_files,
)
from eneo.flows.runtime.step_input_resolution import (
    resolve_step_input as resolve_step_input_runtime,
)
from eneo.flows.runtime.step_result_builder import (
    build_activated_attempt_input,
    build_attempt_provenance,
    build_default_failed_input_payload,
    build_incomplete_attempt_provenance,
    build_terminal_attempt_input,
)
from eneo.flows.runtime.template_fill_runtime import (
    TemplateFillRuntimeDeps,
)
from eneo.flows.runtime.tool_argument_check import ToolArgumentCheckFailed
from eneo.flows.runtime.tool_input import (
    ToolCaller,
    ToolInputDeps,
    pinned_tool_config,
    read_usable_tool,
)
from eneo.flows.runtime.tool_input import (
    resolve_tool_input as resolve_tool_input_runtime,
)
from eneo.flows.runtime.transcription import (
    TranscriptionFailure,
    TranscriptSourcePreparation,
)
from eneo.flows.runtime.transcription_runtime import (
    persist_transcription_on_run_input,
)
from eneo.flows.step_lineage import resolve_step_upstream_orders
from eneo.flows.variable_resolver import FlowVariableContext, FlowVariableResolver
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from eneo.json_types import JsonObject
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    OpenAIException,
    ProviderCapabilityRejectedException,
    ProviderInactiveException,
    ProviderNotFoundException,
    ProviderRejectedRequestException,
    TypedIOValidationException,
)
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserver,
    ProviderCallObserverError,
)
from eneo.model_providers.infrastructure.litellm_provider import (
    load_active_litellm_provider,
)
from eneo.model_providers.infrastructure.litellm_transport import (
    provider_failure_for_code,
)
from eneo.object_content.content import ObjectContentIntegrityError
from eneo.prompts.prompt import Prompt
from eneo.settings.encryption_service import EncryptionService
from eneo.spaces.space_repo import SpaceRepository
from eneo.tasks.contracts import TaskEnqueuer, TaskEnqueueStatus

if TYPE_CHECKING:
    from eneo.assistants.references import ReferencesService
    from eneo.audit.application.audit_service import AuditService
    from eneo.collections.domain.collection import Collection
    from eneo.flows.infrastructure.flow_transcript_words_repo import (
        FlowTranscriptWordsRepository,
    )
    from eneo.flows.runtime.transcription import FlowTranscribers
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.spaces.space import Space
    from eneo.websites.domain.website import Website


_PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV = (
    "ENEO_TEST_FLOW_CRASH_AFTER_ATTEMPT_START_RUN_ID"
)
_PROCESS_TEST_CRASH_EXIT_CODE = 86
_PROVIDER_WORK_AMBIGUITY_DISCLOSURE = (
    "Provider work may or may not have started; retrying can repeat provider work "
    "and spend."
)
_PROVIDER_RESPONSE_RECEIVED_DISCLOSURE = (
    "The provider returned a response; retrying will make a new request "
    "and can incur additional cost."
)


@dataclass(frozen=True, slots=True)
class _ToolPreflight:
    """What one preflight asks about the run's tool steps with: a facts source
    that reads each tool once, so the classification rule and the decision
    judge the same rows, and the space the flow is in."""

    facts: ToolFactsReadOnce
    space_id: UUID
    # By step order, the level the answer of each completed tool step was
    # counted at when it was read.
    recorded_levels: Mapping[int, int | None]


@dataclass(frozen=True, slots=True)
class _PendingTranscript:
    """What an attempt's transcription leaves for its activation to publish:
    the transcript source and, while the latest transcript is inline, that
    transcript for the run row. A file-backed one is committed when written."""

    reference: TranscriptSourceReference
    preparation: TranscriptSourcePreparation
    run_transcript: InlineTranscript | None = None


class _FlowDeletedDuringRun(Exception):
    """The run's flow was deleted after the run's last flow-deleted check."""


def _group_attempt_resolved_inputs(
    *edge_groups: Iterable[FlowResolvedInputEdge],
) -> FlowResolvedInputEdgeGrouping:
    try:
        return group_resolved_input_edges(*edge_groups)
    except ValueError as exc:
        raise TypedIOValidationException(
            "Resolved step input evidence exceeded its bounded runtime contract.",
            code=FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value,
        ) from exc


def _with_provider_work_disclosure(
    message: str, *, step: RuntimeStep, completion_received: bool = False
) -> str:
    if not step.may_call_completion_provider:
        return message
    if completion_received:
        return f"{message.rstrip()} {_PROVIDER_RESPONSE_RECEIVED_DISCLOSURE}"
    return f"{message.rstrip()} {_PROVIDER_WORK_AMBIGUITY_DISCLOSURE}"


def _tool_step_failed_before_its_input_was_stored(
    step: RuntimeStep, *, attempt_no: int, state: RunExecutionState | None
) -> bool:
    """Whether a failed attempt is a tool step's whose input was never stored.

    Such an attempt asked no provider for anything: a tool step takes no
    upload to transcribe, and a step's model is called only after the
    attempt's input is stored.
    """
    return (
        state is not None
        and FlowInputSource(step.input_source) is FlowInputSource.TOOL
        and (step.step_id, attempt_no) not in state.activated_attempts
    )


def _details_after_tool_steps(
    details: FlowRunErrorDetails | None,
    *,
    code: FlowApiErrorCode,
    step: RuntimeStep,
    state: RunExecutionState | None,
) -> FlowRunErrorDetails | None:
    """``details`` of the run error of a run that failed at ``step``, with the
    fact that a tool may have been called when ``tool_call_possible`` says so."""
    if state is None or not tool_call_possible(
        tool_step_orders=state.tool_step_orders,
        completed_step_orders=state.completed_by_order,
        failing_step_order=step.step_order,
    ):
        return details
    return after_possible_tool_call(details, code=code)


def _flow_provider_error_code(exc: Exception | None) -> FlowApiErrorCode | None:
    if not isinstance(exc, OpenAIException):
        return None
    if exc.code == "provider_rate_limited":
        return FlowApiErrorCode.PROVIDER_RATE_LIMITED
    # Unreachable, timed out, dropped and overloaded providers each keep their
    # own public code; the transport's code table says which of them mean down.
    failure = provider_failure_for_code(exc.code)
    if failure is not None and failure.unavailable:
        return FlowApiErrorCode.PROVIDER_UNAVAILABLE
    return None


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


@dataclass(frozen=True)
class FlowRunExecutorConfig:
    max_inline_text_bytes: int
    input_limits: FlowInputLimits | None = None
    max_audio_files: int = 10
    max_generic_files: int | None = None
    http_request_timeout_seconds: float = 30.0
    http_max_timeout_seconds: float = 30.0
    http_allow_private_networks: bool = False
    tool_allow_private_networks: bool = True
    # The deployment's ceiling for one MCP tool call.
    tool_call_timeout_seconds: int = 60
    runtime_policy: FlowRuntimePolicy = field(
        default_factory=default_flow_runtime_policy
    )
    mapped_execution_policy: FlowMappedExecutionPolicy = field(
        default_factory=lambda: resolve_flow_mapped_execution_policy(None)
    )
    rag_retrieval_timeout_seconds: float = 30.0
    rag_evidence_policy: FlowRagEvidencePolicy = field(
        default_factory=FlowRagEvidencePolicy
    )
    document_render_limits: DocumentRenderLimits = field(
        default_factory=lambda: DEFAULT_DOCUMENT_RENDER_LIMITS
    )
    # The organization's switch for security classifications. A run is held to
    # the rule unless the tenant turned it off.
    security_classification_enabled: bool = True

    @classmethod
    def from_settings(
        cls,
        *,
        max_inline_text_bytes: int,
        input_limits: FlowInputLimits | None = None,
        max_audio_files: int = 10,
        max_generic_files: int | None = None,
        document_render_limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS,
        runtime_policy: FlowRuntimePolicy | None = None,
        mapped_execution_policy: FlowMappedExecutionPolicy | None = None,
        rag_evidence_policy: FlowRagEvidencePolicy | None = None,
        security_classification_enabled: bool = True,
    ) -> "FlowRunExecutorConfig":
        settings = get_settings()
        resolved_runtime_policy = runtime_policy or default_flow_runtime_policy(
            defaults=settings
        )
        return cls(
            max_inline_text_bytes=max_inline_text_bytes,
            input_limits=input_limits,
            max_audio_files=max_audio_files,
            max_generic_files=max_generic_files,
            http_request_timeout_seconds=float(
                settings.flow_http_request_timeout_seconds
            ),
            http_max_timeout_seconds=float(settings.flow_http_max_timeout_seconds),
            http_allow_private_networks=bool(settings.flow_http_allow_private_networks),
            tool_allow_private_networks=bool(settings.flow_tool_allow_private_networks),
            tool_call_timeout_seconds=settings.mcp_client_call_timeout_seconds,
            runtime_policy=resolved_runtime_policy,
            mapped_execution_policy=(
                mapped_execution_policy or resolve_flow_mapped_execution_policy(None)
            ),
            rag_evidence_policy=rag_evidence_policy or FlowRagEvidencePolicy(),
            document_render_limits=document_render_limits,
            security_classification_enabled=security_classification_enabled,
        )

    def step_deadline_seconds(self, step: RuntimeStep) -> float:
        return float(
            resolve_step_timeout_seconds(
                step_order=step.step_order,
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


def _attempt_completion_evidence(
    prepared_steps: Sequence[PreparedAssistantStep],
) -> tuple[
    FlowStepAttemptCompletionConfiguration,
    tuple[FlowStepAttemptExecutionInput, ...],
]:
    calls = tuple(step.prepared.completion_call for step in prepared_steps)
    if not calls or any(call is None for call in calls):
        raise FlowRuntimeInvariantError(
            "Flow provider-call inputs must be frozen before attempt activation."
        )
    frozen_calls = tuple(call for call in calls if call is not None)
    first = frozen_calls[0]
    if any(
        call.preferred_model_parameters != first.preferred_model_parameters
        or call.capability_fallback_model_parameters
        != first.capability_fallback_model_parameters
        for call in frozen_calls[1:]
    ):
        raise FlowRuntimeInvariantError(
            "Mapped Flow calls must share one completion configuration."
        )
    return (
        FlowStepAttemptCompletionConfiguration(
            preferred_model_parameters=cast(
                JsonObject, first.preferred_model_parameters
            ),
            capability_fallback_model_parameters=cast(
                JsonObject | None,
                first.capability_fallback_model_parameters,
            ),
        ),
        tuple(
            FlowStepAttemptExecutionInput(
                question=utf8_prefix(
                    call.question,
                    max_bytes=prepared.deps.max_inline_text_bytes,
                ),
                question_truncated=len(call.question.encode("utf-8"))
                > prepared.deps.max_inline_text_bytes,
                material_aliases=build_step_material_aliases(
                    materials=prepared.prepared.step_input.materials,
                    max_inline_bytes=prepared.deps.max_inline_text_bytes,
                ),
                effective_prompt=utf8_prefix(
                    call.effective_prompt,
                    max_bytes=prepared.deps.max_inline_text_bytes,
                ),
                effective_prompt_truncated=len(call.effective_prompt.encode("utf-8"))
                > prepared.deps.max_inline_text_bytes,
                assistant_context_version=call.assistant_context_version,
            )
            for call, prepared in zip(frozen_calls, prepared_steps, strict=True)
        ),
    )


def _start_describes_a_completion_request(start: FlowStepAttemptStart | None) -> bool:
    return start is not None and (
        start.requested_model is not None
        or start.provider is not None
        or start.mapped_admission is not None
    )


def _attempt_start_for_step(
    *,
    state: RunExecutionState | None,
    step: RuntimeStep,
) -> FlowStepAttemptStart | None:
    if state is None:
        return None
    return state.attempt_start_by_step.get(step.step_id)


def _failed_item_counts(exc: BaseException | None) -> tuple[int | None, int | None]:
    """Mapped item progress at failure.

    A mapped handler records its counts on the error as it leaves, so they win
    over the step-progress snapshot a deadline error took when it was raised.
    """
    evidence = failure_evidence(exc)
    deadline = exc if isinstance(exc, StepDeadlineExceeded) else None
    completed_items = evidence.completed_items
    if completed_items is None and deadline is not None:
        completed_items = deadline.completed_items
    total_items = evidence.total_items
    if total_items is None and deadline is not None:
        total_items = deadline.total_items
    return completed_items, total_items


def _pre_attempt_start_model_from_state_cache(
    *,
    state: RunExecutionState | None,
    step: RuntimeStep,
) -> tuple[str | None, str | None]:
    # Preparation can fail after the assistant is loaded but before
    # attempt_start is persisted; preserve model triage data in that window.
    # A step that calls no completion model has none to report.
    if (
        state is None
        or step.assistant_snapshot is None
        or not step.may_call_completion_provider
    ):
        return None, None
    assistant = state.assistant_cache.get(
        assistant_cache_key(step.assistant_id, step.assistant_snapshot)
    )
    if assistant is None:
        return None, None
    return (
        _requested_model_from_assistant(assistant),
        _provider_from_assistant(assistant),
    )


class FlowRunExecutor:
    """Executes a version-pinned flow run sequentially with CAS step claims."""

    def __init__(
        self,
        *,
        runtime_actor: FlowRunActor,
        session: AsyncSession,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        flow_run_review_checkpoint_repo: FlowRunReviewCheckpointRepository,
        flow_version_repo: FlowVersionRepository,
        space_repo: SpaceRepository,
        completion_service: CompletionService,
        file_repo: FileRepository,
        file_content_loader: FileContentLoader,
        file_service: FileService,
        template_asset_repo: FlowTemplateAssetRepository,
        encryption_service: EncryptionService,
        flow_run_terminalizer: FlowRunTerminalizer,
        max_inline_text_bytes: int | None = None,
        input_limits: FlowInputLimits | None = None,
        audit_service: AuditService | None = None,
        read_audit_service: Callable[
            [], AbstractAsyncContextManager[AuditService | None]
        ],
        webhook_delivery_repo: FlowRunWebhookDeliveryRepository | None = None,
        task_enqueuer: TaskEnqueuer | None = None,
        references_service: ReferencesService | None = None,
        transcribers: FlowTranscribers | None = None,
        max_audio_files: int = 10,
        max_generic_files: int | None = None,
        config: FlowRunExecutorConfig | None = None,
        transcript_words_repo: "FlowTranscriptWordsRepository | None" = None,
        invocation_deadline: float | None = None,
        tool_facts_reader: UnattendedToolFactsSource | None = None,
        tool_caller: ToolCaller | None = None,
    ) -> None:
        resolved_config = config
        if resolved_config is None:
            if max_inline_text_bytes is None:
                raise TypeError(
                    "FlowRunExecutor requires max_inline_text_bytes or config."
                )
            resolved_config = FlowRunExecutorConfig.from_settings(
                max_inline_text_bytes=max_inline_text_bytes,
                input_limits=input_limits,
                max_audio_files=max_audio_files,
                max_generic_files=max_generic_files,
            )

        self.runtime_actor = runtime_actor
        self.principal = runtime_actor.principal
        self.session = session
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.transcript_words_repo = transcript_words_repo
        self._pending_transcript_sources: dict[
            tuple[UUID, UUID, int], _PendingTranscript
        ] = {}
        self.flow_run_review_checkpoint_repo = flow_run_review_checkpoint_repo
        self.flow_run_terminalizer = flow_run_terminalizer
        self.webhook_delivery_repo = (
            webhook_delivery_repo
            if webhook_delivery_repo is not None
            else FlowRunWebhookDeliveryRepository(session=session)
        )
        self.task_enqueuer = task_enqueuer
        self.flow_version_repo = flow_version_repo
        self.space_repo = space_repo
        self.completion_service = completion_service
        self.file_repo = file_repo
        self.file_content_loader = file_content_loader
        self.file_service = file_service
        self.template_asset_repo = template_asset_repo
        self.encryption_service = encryption_service
        self.max_inline_text_bytes = resolved_config.max_inline_text_bytes
        self.audit_service = audit_service
        # Opens the audit service a tool or HTTP input read queues its record
        # with, on a database session that is not the run's: a write that
        # outlives its time limit is left to unwind there.
        self.read_audit_service = read_audit_service
        self.references_service = references_service
        self.transcribers = transcribers
        # Per-run document names, derived from the pinned definition with the steps.
        self.generated_file_names: GeneratedFileNames | None = None
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
        self.tool_facts_reader = tool_facts_reader
        self.tool_caller = tool_caller
        self.tool_destination_policy = FlowDestinationPolicy(
            allow_private_networks=resolved_config.tool_allow_private_networks,
            traffic=FlowOutboundTraffic.MCP_TOOL_CALL,
        )
        self.tool_name_resolver: Resolver = flow_name_resolver()
        self.tool_call_timeout_seconds = resolved_config.tool_call_timeout_seconds
        self.runtime_policy = resolved_config.runtime_policy
        self.mapped_execution_policy = resolved_config.mapped_execution_policy
        self._step_deadline_seconds = resolved_config.step_deadline_seconds
        self.invocation_deadline = invocation_deadline
        # The budget of the attempt currently executing; every dependency
        # built while it is set shares it (mapped previews rebuild deps per
        # item and must not restart the clock).
        self._active_step_deadline: StepDeadline | None = None
        self.rag_retrieval_timeout_seconds = (
            resolved_config.rag_retrieval_timeout_seconds
        )
        self.document_render_service: DocumentRenderService = (
            default_document_render_service(
                limits=resolved_config.document_render_limits
            )
        )
        self.rag_evidence_policy = resolved_config.rag_evidence_policy
        self.security_classification_enabled = (
            resolved_config.security_classification_enabled
        )
        self.max_audio_files = resolved_config.max_audio_files
        self.max_generic_files = resolved_config.max_generic_files
        self.input_limits = resolved_config.input_limits

    @property
    def session(self) -> AsyncSession:
        return self._session

    @session.setter
    def session(self, session: AsyncSession) -> None:
        # Watched from the moment the executor runs on it, so
        # _end_read_transaction can tell a transaction that has only read.
        previous = getattr(self, "_transaction_writes", None)
        if previous is not None:
            if self._session is session:
                return
            previous.stop()
        self._session = session
        self._transaction_writes = TransactionWrites(session)

    async def execute(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        run_revision: int,
        dispatch_task_id: str | None,
        retry_count: int,
    ) -> dict[str, object]:
        # Read before the claim stamps the lease, so its commit counts
        # against the lease the heartbeats then keep.
        leased_at = time.monotonic()
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

        try:
            async with execution_heartbeats().track(
                FlowRunExecutionOwner(run_id, tenant_id, run_revision),
                leased_at=leased_at,
            ):
                return await self.execute_claimed(
                    run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    dispatch_task_id=dispatch_task_id,
                    retry_count=retry_count,
                )
        except FlowExecutionOwnershipLost:
            await self._rollback()
            return await self._return_after_losing_the_run(
                run_id=run_id, flow_id=flow_id, tenant_id=tenant_id
            )

    async def execute_claimed(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        dispatch_task_id: str | None,
        retry_count: int,
    ) -> dict[str, Any]:
        logger.info(
            "flow_executor.start run_id=%s flow_id=%s tenant_id=%s task_retry_count=%d",
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
            return await self._cancel_run_of_deleted_flow(
                run_id=run_id,
                tenant_id=tenant_id,
                message="Flow was deleted before execution started.",
            )

        version = await self.flow_version_repo.get(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=tenant_id,
        )
        try:
            published_definition = parse_verified_published_definition(
                version.definition_json,
                expected_flow_id=run.flow_id,
                expected_checksum=version.definition_checksum,
                flow_version=version.version,
            )
            steps = published_definition.runtime_steps()
            self.generated_file_names = GeneratedFileNames.for_run(
                flow_name=published_definition.name,
                steps=steps,
                run_created_at=run.created_at,
            )
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
        payloads = await self.flow_run_review_checkpoint_repo.list_resumed_json_review_payloads(
            run_id=run_id,
            tenant_id=tenant_id,
            attempts=reviewed_result_attempts(persisted_results),
            max_rows=REVIEWED_EDIT_READ_MAX_ROWS,
            max_logical_bytes=REVIEWED_EDIT_READ_MAX_LOGICAL_BYTES,
        )
        if payloads is None:
            code = FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE
            await self._terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=FlowRunLifecycleSource.EXECUTOR_FAILED,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.EXECUTOR_FAILED,
                    code=code,
                    message="The run's reviewed edits exceed the read limit.",
                ),
            )
            await self._commit()
            return {"status": "failed", "error": code.value}
        state = build_run_execution_state(
            steps=steps,
            persisted_results=persisted_results,
            flow_id=flow_id,
            reviewed_results=reviewed_results(payloads, steps=steps),
        )
        # The state holds what the steps read of these rows; the full rows
        # would otherwise stay alive for the rest of the run.
        del persisted_results, payloads
        try:
            await self._validate_assistant_snapshots(
                steps=steps,
                state=state,
                run_id=run_id,
            )
        except _FlowDeletedDuringRun:
            return await self._cancel_run_of_deleted_flow(
                run_id=run_id,
                tenant_id=tenant_id,
                message="Flow was deleted during execution.",
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

        logger.info(
            "flow_executor.steps_parsed run_id=%s step_count=%d", run_id, len(steps)
        )
        try:
            self._refuse_unacceptable_http_configs(steps)
            await self._refuse_model_steps_without_a_model(steps, state=state)
            tool_preflight = await self._tool_preflight(steps, run=run, state=state)
            step_output_levels = await self._resolve_step_output_levels(
                steps=steps, state=state, run=run, tool_preflight=tool_preflight
            )
        except BadRequestException as exc:
            return await self._fail_run_before_its_steps(
                exc,
                run_id=run_id,
                tenant_id=tenant_id,
                source=FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
            )
        try:
            await self._refuse_unusable_tools(
                steps, run=run, state=state, tool_preflight=tool_preflight
            )
        except TypedIOValidationException as exc:
            # What a level decides about a tool is no fault of the definition:
            # the run ends with the code, the source and the typed details it
            # would have at the step that meets the same refusal. Its message
            # is the refusal's own sentence, which at the step is the step
            # attempt's.
            return await self._fail_run_before_its_steps(
                exc,
                run_id=run_id,
                tenant_id=tenant_id,
                source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            )
        await self.flow_run_repo.record_evidence_classification_level(
            run_id=run_id,
            tenant_id=tenant_id,
            level=evidence_classification_level(step_output_levels),
            has_completed_steps=bool(state.completed_by_order),
        )
        # Each step reads the run again; this copy, with its input, is done.
        del run
        for step in sorted(steps, key=lambda item: item.step_order):
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
                return await self._cancel_run_of_deleted_flow(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    message=preclaim_decision.run_error_message
                    or "Flow was deleted during execution.",
                )

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
                # The re-read row lives on in the decision only, which ends
                # with this step too: a completed row must not outlast its
                # projection into the state.
                del existing, claim_resolution
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
                    del postclaim_decision
                    continue
                if postclaim_decision.action == "continue":
                    del postclaim_decision
                    continue

            claimed_result = cast(FlowStepResult, claimed)
            try:
                started_attempt = await self._start_step_attempt(
                    run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step=step,
                    dispatch_task_id=dispatch_task_id,
                )
                await self._commit()
                # A zero-model step can cross this commit before an external test
                # can stop it; exact test mode and run identity keep the exit inert.
                if get_settings().testing and os.environ.get(
                    _PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV
                ) == str(run_id):
                    os._exit(_PROCESS_TEST_CRASH_EXIT_CODE)
            except Exception:
                return await self._handle_attempt_start_failure(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    step=step,
                    claimed=claimed_result,
                    state=state,
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
            except FlowStepAttemptClosed:
                await self._rollback()
                return await self._return_after_losing_the_run(
                    run_id=run_id, flow_id=flow_id, tenant_id=tenant_id
                )
            except TypedIOValidationException as typed_exc:
                contract_diag: dict[str, Any] | None = None
                failed_input_payload = typed_exc.input_payload_json
                resolved_input_source = step.input_source
                if failed_input_payload is not None:
                    raw_contract_diag = failed_input_payload.get("contract_validation")
                    contract_diag = (
                        cast(dict[str, Any], raw_contract_diag)
                        if isinstance(raw_contract_diag, dict)
                        else None
                    )
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
                    failed_input_payload=failed_input_payload,
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
            # Only the delivery intents are read past this point; the step's
            # output and the rows built and saved for it would otherwise stay
            # alive through the next step.
            delivery_intents = success_plan.delivery_intents
            del execution_result, output, success_plan, step_result
            del persisted_step_result

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

            if delivery_intents:
                for delivery_intent in delivery_intents:
                    await self.webhook_delivery_repo.insert_pending_delivery(
                        flow_id=flow_id,
                        tenant_id=tenant_id,
                        intent=delivery_intent,
                    )
                await self._commit()
                await self._request_webhook_delivery(run_id=run_id)
                return {"status": FlowRunStatus.RUNNING.value}

        finalization = await finalize_run_from_current_results(
            run_id=run_id,
            tenant_id=tenant_id,
            flow_run_repo=self.flow_run_repo,
            terminalizer=self.flow_run_terminalizer,
            principal=self.principal,
        )
        await self._commit()
        return finalization.payload

    async def _start_step_attempt(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step: RuntimeStep,
        dispatch_task_id: str | None,
    ) -> FlowStepAttempt:
        attempt_no = await self.flow_run_repo.allocate_next_attempt_no(
            tenant_id=tenant_id,
            flow_run_id=run_id,
            step_id=step.step_id,
        )
        return await self.flow_run_repo.create_or_get_attempt_started(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            step_id=step.step_id,
            step_order=step.step_order,
            attempt_no=attempt_no,
            dispatch_task_id=dispatch_task_id,
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
                flow_id=run.flow_id,
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
        state.material_cache = {}
        state.resolved_materials = ()
        deadline = self._start_step_deadline(step)
        self._active_step_deadline = deadline
        try:
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
                backstop: asyncio.Timeout | None = None
                # The scope stays published while a timeout is converted, so the
                # message can read the progress and in-flight facts the phases
                # recorded in it.
                with step_deadline_scope(deadline, step_order=step.step_order):
                    record_step_phase(FlowStepPhase.STEP_EXECUTION)
                    require_step_budget(phase="step execution")
                    try:
                        # Backstop for phases that cannot check the budget
                        # themselves (decoding, extraction, a stalled
                        # retrieval). Phases that can (mapped items, provider
                        # waits, transcription requests) refuse earlier with a
                        # more precise message through the published scope.
                        async with asyncio.timeout(
                            deadline.remaining()
                            + step_deadline_module.STEP_DEADLINE_BACKSTOP_GRACE_SECONDS
                        ) as backstop:
                            result = await handler.execute(
                                step=step,
                                run=run,
                                state=state,
                                version_metadata=version_metadata,
                                attempt_no=attempt_no,
                            )
                            if (
                                run.id,
                                step.step_id,
                                attempt_no,
                            ) in self._pending_transcript_sources:
                                # Activation publishes the transcript and its
                                # source; without it both would be lost.
                                raise FlowRuntimeInvariantError(
                                    "A step that transcribed audio completed "
                                    "without activating its attempt "
                                    f"(step_id={step.step_id}, "
                                    f"attempt_no={attempt_no})."
                                )
                            result.output.materials = state.resolved_materials
                            result.output.max_inline_text_bytes = (
                                self.max_inline_text_bytes
                            )
                    except TypedIOValidationException as exc:
                        prompt = exc.effective_prompt
                        if prompt is not None:
                            exc.effective_prompt = utf8_prefix(
                                prompt, max_bytes=self.max_inline_text_bytes
                            )
                            exc.input_payload_json = {
                                **(exc.input_payload_json or {}),
                                "effective_prompt_truncated": len(
                                    prompt.encode("utf-8")
                                )
                                > self.max_inline_text_bytes,
                            }
                        raise
                    except TimeoutError as exc:
                        if backstop is None or not backstop.expired():
                            # Some inner wait timed out on its own; only the
                            # backstop's expiry is the step's budget running out.
                            raise
                        typed = deadline.timeout_error(
                            step_order=step.step_order, phase="step execution"
                        )
                        # asyncio.timeout chains the cancellation it converted;
                        # the runtime and the mapped handlers hang their
                        # completed-call evidence on that cancellation (or on
                        # the error itself).
                        partial_evidence = failure_evidence(exc).rag_metadata
                        if partial_evidence is None:
                            partial_evidence = failure_evidence(
                                exc.__cause__
                            ).rag_metadata
                        if partial_evidence is not None:
                            attach_failure_evidence(
                                typed, rag_metadata=partial_evidence
                            )
                        raise typed from exc
                    record_step_phase(FlowStepPhase.FINALIZATION)
                    if deadline.expired():
                        # Finished inside the grace, after the budget: the
                        # budget is the contract, so the result is not accepted
                        # as a completed step; what it retrieved is evidence.
                        late = deadline.timeout_error(
                            step_order=step.step_order,
                            phase="finalization (the result completed after the budget)",
                            provider_request_in_flight=False,
                        )
                        if result.output.rag_metadata is not None:
                            attach_failure_evidence(
                                late, rag_metadata=result.output.rag_metadata
                            )
                        raise late
                step_span.set_result(status="completed")
                return result
        finally:
            self._active_step_deadline = None
            state.material_cache = None
            state.resolved_materials = ()

    def _start_step_deadline(self, step: RuntimeStep) -> StepDeadline:
        try:
            budget_seconds = self._step_deadline_seconds(step)
        except BadRequestException as exc:
            raise TypedIOValidationException(
                str(exc),
                code=exc.code,
                context=exc.context,
            ) from exc
        invocation_limited = False
        if self.invocation_deadline is not None:
            remaining = (
                self.invocation_deadline
                - asyncio.get_running_loop().time()
                - STEP_TIMEOUT_TASK_BUFFER_SECONDS
            )
            invocation_limited = remaining <= budget_seconds
            budget_seconds = min(budget_seconds, max(0.0, remaining))
        return StepDeadline.start(budget_seconds, invocation_limited=invocation_limited)

    def _build_step_handler(self, mode: FlowOutputMode) -> StepHandler:
        match mode:
            case FlowOutputMode.PASS_THROUGH:
                return PassThroughStepHandler(
                    prepare_assistant_step=self._prepare_assistant_step,
                    preview_assistant_step=self._preview_assistant_step,
                    list_step_input_file_ids=self._list_step_input_file_ids,
                    activate_prepared_assistant_steps=(
                        self._activate_prepared_assistant_steps
                    ),
                    mapped_execution_policy=self.mapped_execution_policy,
                    rag_evidence_policy=self.rag_evidence_policy,
                )
            case FlowOutputMode.COPY_INPUT:
                return CopyInputStepHandler(
                    prepare_assistant_step=self._prepare_assistant_step
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
                        activate_prepared_assistant_steps=(
                            self._activate_prepared_assistant_steps
                        ),
                        mapped_execution_policy=self.mapped_execution_policy,
                        rag_evidence_policy=self.rag_evidence_policy,
                    )
                )
            case FlowOutputMode.TRANSCRIBE_ONLY:
                return TranscribeOnlyStepHandler(
                    prepare_assistant_step=self._prepare_assistant_step
                )
            case FlowOutputMode.TEMPLATE_FILL:
                return TemplateFillStepHandler(
                    deps=self._template_fill_runtime_deps(),
                    activate_resolved_input_edges=self._activate_resolved_input_edges,
                )
            case FlowOutputMode.RENDER_VERBATIM:
                return RenderVerbatimStepHandler(
                    prepare_assistant_step=self._prepare_assistant_step
                )
            case FlowOutputMode.SPEAKER_MAPPING:
                return SpeakerMappingStepHandler(
                    preview_assistant_step=self._preview_assistant_step,
                    activate_prepared_assistant_steps=(
                        self._activate_prepared_assistant_steps
                    ),
                    activate_resolved_input_edges=self._activate_resolved_input_edges,
                    persist_transcript=self._persist_run_transcript,
                    transcript_source_for_step=self._transcript_source_for_step,
                )
        assert_never(mode)

    async def _transcript_source_for_step(
        self, run: FlowRun, result: FlowStepResult
    ) -> TranscriptSourceReference | None:
        from eneo.flows.application.flow_transcript_source_service import (
            resolve_transcript_source_reference,
        )
        from eneo.main.exceptions import NotFoundException

        if result.current_attempt_no is None:
            return None
        attempt = await self.flow_run_repo.get_step_attempt(
            run_id=run.id,
            tenant_id=run.tenant_id,
            step_id=result.step_id,
            attempt_no=result.current_attempt_no,
        )
        if attempt is None:
            raise NotFoundException("Flow run step attempt not found.")
        return await resolve_transcript_source_reference(
            attempt=attempt,
            transcript_source_repo=FlowTranscriptSourceRepository(session=self.session),
        )

    async def _persist_run_transcript(
        self, run: FlowRun, transcript: InlineTranscript
    ) -> None:
        await persist_transcription_on_run_input(
            flow_run_repo=self.flow_run_repo, run=run, transcript=transcript
        )

    def _template_fill_runtime_deps(self) -> TemplateFillRuntimeDeps:
        return TemplateFillRuntimeDeps(
            variable_resolver=self.variable_resolver,
            file_repo=self.file_repo,
            file_content_loader=self.file_content_loader,
            file_service=self.file_service,
            template_asset_repo=self.template_asset_repo,
            logger=logger,
            file_names=self._file_names(),
        )

    def _file_names(self) -> GeneratedFileNames:
        if self.generated_file_names is None:
            raise RuntimeError("A step ran before the run's definition was parsed.")
        return self.generated_file_names

    def _build_step_execution_runtime_deps(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        attempt_no: int,
    ) -> StepExecutionRuntimeDeps:
        deadline = self._active_step_deadline or self._start_step_deadline(step)

        return StepExecutionRuntimeDeps(
            variable_resolver=self.variable_resolver,
            completion_service=self.completion_service,
            load_assistant=self._load_assistant,
            resolve_step_input=partial(self._resolve_step_input, attempt_no=attempt_no),
            retrieve_rag_chunks=self._retrieve_rag_chunks,
            process_typed_output=self._process_typed_output,
            apply_output_cap=self._apply_output_cap,
            max_inline_text_bytes=self.max_inline_text_bytes,
            logger=logger,
            llm_request_timeout_seconds=deadline.budget_seconds,
            deadline=deadline,
            rag_retrieval_timeout_seconds=self.rag_retrieval_timeout_seconds,
            run_cancelled=self._run_is_cancelled,
            build_provider_call_observer=lambda mapped_call,
            resolved_input_edge_indexes,
            completion_model_id,
            summarization_input=None,
            summarization=None,
            digest_call=None: FlowProviderCallRecorder(
                run_id=run.id,
                step_id=step.step_id,
                attempt_no=attempt_no,
                tenant_id=run.tenant_id,
                principal_user_id=run.principal_user_id,
                principal_service_id=run.principal_service_id,
                completion_model_id=completion_model_id,
                mapped_call=mapped_call,
                resolved_input_edge_indexes=resolved_input_edge_indexes,
                summarization_input=summarization_input,
                summarization=summarization,
                digest_call=digest_call,
                before_request=self._end_read_transaction,
            ),
            persist_summarization=partial(
                self._persist_summarization,
                run=run,
                step=step,
                attempt_no=attempt_no,
            ),
            # Transcription runs while the step input is still being produced,
            # so it has neither a mapped call nor a resolved input aggregate.
            build_transcription_call_observer=lambda: FlowProviderCallRecorder(
                run_id=run.id,
                step_id=step.step_id,
                attempt_no=attempt_no,
                tenant_id=run.tenant_id,
                principal_user_id=run.principal_user_id,
                principal_service_id=run.principal_service_id,
                completion_model_id=None,
                mapped_call=None,
                resolved_input_edge_indexes=(),
                before_request=self._end_read_transaction,
            ),
        )

    async def _persist_summarization(
        self,
        summarization: SummarizationProvenance,
        *,
        run: FlowRun,
        step: RuntimeStep,
        attempt_no: int,
    ) -> None:
        async with sessionmanager.session() as session, session.begin():
            await FlowProviderCallRepository(
                session
            ).persist_summarization_for_execution(
                run_id=run.id,
                step_id=step.step_id,
                attempt_no=attempt_no,
                tenant_id=run.tenant_id,
                summarization=summarization,
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
        if step.may_call_completion_provider:
            prepared = replace(
                prepared,
                completion_call=build_prepared_completion_call(
                    step=step,
                    state=state,
                    prepared=prepared,
                ),
            )
        prepared_step = PreparedAssistantStep(prepared=prepared, deps=execution_deps)
        attempt_start = self._build_attempt_start(
            step=step,
            state=state,
            prepared_step=prepared_step,
        )
        requested_model = attempt_start.requested_model
        provider = attempt_start.provider
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
        grouping = _group_attempt_resolved_inputs(prepared.resolved_input_edges)
        completion_configuration: FlowStepAttemptCompletionConfiguration | None = None
        execution_inputs: tuple[FlowStepAttemptExecutionInput, ...] = ()
        if step.may_call_completion_provider:
            completion_configuration, execution_inputs = _attempt_completion_evidence(
                (prepared_step,)
            )
        await self._activate_step_attempt(
            run=run,
            step=step,
            state=state,
            attempt_no=attempt_no,
            resolved_input_edges=grouping.aggregate,
            attempt_start=attempt_start,
            resolved_input=cast(JsonObject, prepared.input_payload_for_result),
            completion_configuration=completion_configuration,
            execution_inputs=execution_inputs,
        )
        return PreparedAssistantStep(
            prepared=replace(
                prepared,
                resolved_input_edge_indexes=grouping.indexes_by_group[0],
            ),
            deps=execution_deps,
        )

    @staticmethod
    def _build_attempt_start(
        *,
        step: RuntimeStep,
        state: RunExecutionState,
        prepared_step: PreparedAssistantStep,
    ) -> FlowStepAttemptStart:
        prepared = prepared_step.prepared
        resolved_timeout_seconds = int(prepared_step.deps.llm_request_timeout_seconds)
        input_text_length = len(prepared.step_input.text)
        if not step.may_call_completion_provider:
            # The step's assistant has a completion model, but this step asks
            # it nothing, so the attempt names none.
            return FlowStepAttemptStart(
                resolved_timeout_seconds=resolved_timeout_seconds,
                input_text_length=input_text_length,
            )
        return FlowStepAttemptStart(
            requested_model=_requested_model_from_assistant(prepared.assistant),
            provider=_provider_from_assistant(prepared.assistant),
            resolved_timeout_seconds=resolved_timeout_seconds,
            input_text_length=input_text_length,
            mapped_admission=state.mapped_admission_by_step.get(step.step_id),
        )

    async def _activate_prepared_assistant_steps(
        self,
        run: FlowRun,
        step: RuntimeStep,
        state: RunExecutionState,
        attempt_no: int,
        prepared_steps: Sequence[PreparedAssistantStep],
    ) -> tuple[PreparedAssistantStep, ...]:
        if not prepared_steps:
            raise FlowRuntimeInvariantError(
                "Mapped Flow step attempt has no prepared provider calls."
            )
        grouping = _group_attempt_resolved_inputs(
            *(prepared.prepared.resolved_input_edges for prepared in prepared_steps)
        )
        pending_source = self._pending_transcript_sources.get(
            (run.id, step.step_id, attempt_no)
        )
        if pending_source is not None:
            for prepared_step in prepared_steps:
                metadata = prepared_step.prepared.step_input.transcription_metadata
                if metadata is not None:
                    metadata["source"] = pending_source.reference.model_dump(
                        mode="json"
                    )
        completion_configuration, execution_inputs = _attempt_completion_evidence(
            prepared_steps
        )
        await self._activate_step_attempt(
            run=run,
            step=step,
            state=state,
            attempt_no=attempt_no,
            resolved_input_edges=grouping.aggregate,
            attempt_start=self._build_attempt_start(
                step=step,
                state=state,
                prepared_step=prepared_steps[0],
            ),
            completion_configuration=completion_configuration,
            execution_inputs=execution_inputs,
        )
        return tuple(
            PreparedAssistantStep(
                prepared=replace(
                    prepared_step.prepared,
                    resolved_input_edge_indexes=indexes,
                ),
                deps=prepared_step.deps,
            )
            for prepared_step, indexes in zip(
                prepared_steps,
                grouping.indexes_by_group,
                strict=True,
            )
        )

    async def _activate_step_attempt(
        self,
        *,
        run: FlowRun,
        step: RuntimeStep,
        state: RunExecutionState,
        attempt_no: int,
        resolved_input_edges: FlowResolvedInputEdges,
        attempt_start: FlowStepAttemptStart | None,
        resolved_input: JsonObject | None = None,
        completion_configuration: FlowStepAttemptCompletionConfiguration | None = None,
        execution_inputs: tuple[FlowStepAttemptExecutionInput, ...] = (),
    ) -> None:
        activation_key = (step.step_id, attempt_no)
        if activation_key in state.activated_attempts:
            raise FlowRuntimeInvariantError(
                "Flow step attempt input evidence was activated more than once "
                f"(step_id={step.step_id}, attempt_no={attempt_no})."
            )
        if not step.may_call_completion_provider and (
            completion_configuration is not None
            or execution_inputs
            or _start_describes_a_completion_request(attempt_start)
        ):
            raise FlowRuntimeInvariantError(
                "Flow step attempt evidence described a completion request for "
                "a step that calls no completion model "
                f"(step_id={step.step_id}, attempt_no={attempt_no})."
            )
        pending_source = self._pending_transcript_sources.get(
            (run.id, step.step_id, attempt_no)
        )
        if pending_source is not None:
            resolved_input = with_transcript_source_reference(
                resolved_input, pending_source.reference
            )
        activated = await self.flow_run_repo.activate_step_attempt(
            run_id=run.id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=run.tenant_id,
            resolved_input_edges=resolved_input_edges,
            attempt_input=build_activated_attempt_input(
                start=attempt_start,
                resolved_input=resolved_input,
                completion_configuration=completion_configuration,
                execution_inputs=execution_inputs,
            ),
        )
        if activated is None:
            raise FlowRuntimeInvariantError(
                "Flow step attempt closed before input evidence activation "
                f"(step_id={step.step_id}, attempt_no={attempt_no})."
            )
        if pending_source is not None and pending_source.run_transcript is not None:
            # The run row is already locked by the activation above.
            await self._persist_run_transcript(run, pending_source.run_transcript)
        await self._publish_transcript_source(
            run_id=run.id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=run.tenant_id,
            flow_id=run.flow_id,
        )
        await self._commit()
        self._forget_pending_transcript(run.id, step.step_id, attempt_no)
        if attempt_start is not None:
            persisted_attempt_input = parse_flow_step_attempt_input(
                activated.input_payload_json
            ).attempt_input
            if (
                persisted_attempt_input is None
                or persisted_attempt_input.start is None
                or (
                    step.may_call_completion_provider
                    and persisted_attempt_input.execution_inputs is None
                )
            ):
                raise FlowRuntimeInvariantError(
                    "Flow step attempt input evidence was activated without "
                    "its start and exact execution inputs."
                )
            state.attempt_start_by_step[step.step_id] = persisted_attempt_input.start
        state.activated_attempts.add(activation_key)

    async def _activate_resolved_input_edges(
        self,
        run: FlowRun,
        step: RuntimeStep,
        state: RunExecutionState,
        attempt_no: int,
        resolved_input_edges: tuple[FlowResolvedInputEdge, ...],
    ) -> None:
        aggregate = _group_attempt_resolved_inputs(resolved_input_edges).aggregate
        await self._activate_step_attempt(
            run=run,
            step=step,
            state=state,
            attempt_no=attempt_no,
            resolved_input_edges=aggregate,
            attempt_start=None,
        )

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
        """Prepare mapped input without recording attempt-start. Nothing is
        committed, except for a step whose input is a tool: section processing
        previews the step's own input, and that read commits the record of its
        call before the request (once per attempt)."""
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
        if requested_file_ids:
            await admit_runtime_files(
                run=run,
                requested_ids=list(requested_file_ids),
                state=state,
                deps=self._build_step_input_resolution_deps(attempt_no=attempt_no),
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
        prepared = replace(
            prepared,
            completion_call=build_prepared_completion_call(
                step=step,
                state=state,
                prepared=prepared,
            ),
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
            evidence_policy=self.rag_evidence_policy,
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
        """Read the run's cancellation state in its own short transaction.

        This is polled while a provider call is in flight, so it must not run on
        the executor's session: a failed statement there leaves the transaction
        unusable and every later probe would fail with it, and even successful
        probes would hold that connection checked out for the length of the
        call. Isolated short transactions are the same shape the provider-call
        recorder uses for the same reason.
        """
        ownership_lost = await execution_ownership_is_lost()
        if ownership_lost is not None:
            return ownership_lost
        async with sessionmanager.session() as session, session.begin():
            run = await FlowRunRepository(session=session).get(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
            )
        return run.status != FlowRunStatus.RUNNING

    async def _return_after_losing_the_run(
        self, *, run_id: UUID, flow_id: UUID, tenant_id: UUID
    ) -> dict[str, Any]:
        # The run was lost either because it was terminalized (report the
        # honest terminal outcome, as a late write always did) or because
        # recovery gave it to another owner or back to the queue (only then
        # is "ownership lost" the whole truth). Either way no transcript the
        # run staged is published.
        for run_id_, step_id, attempt_no in list(self._pending_transcript_sources):
            if run_id_ == run_id:
                self._forget_pending_transcript(run_id, step_id, attempt_no)
        try:
            return await self._return_after_terminalized_step_write(
                run_id=run_id, flow_id=flow_id, tenant_id=tenant_id
            )
        except RuntimeError:
            return {"status": "skipped", "reason": "execution_ownership_lost"}

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
        state: RunExecutionState,
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
        saved_result = await self.flow_run_repo.save_step_result(
            run_id,
            failure_plan.failed_result,
            tenant_id=tenant_id,
            attempt_no=None,
        )
        # Terminalization won the race; report the persisted run outcome rather
        # than this step's failure.
        if saved_result is None:
            await self._commit()
            return await self._return_after_terminalized_step_write(
                run_id=run_id,
                flow_id=claimed.flow_id,
                tenant_id=tenant_id,
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
                details=_details_after_tool_steps(
                    None, code=run_error_code, step=step, state=state
                ),
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
        self._forget_pending_transcript(run_id, step.step_id, attempt_no)
        if current_execution_ownership_lost():
            raise FlowExecutionOwnershipLost()
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
        # A step that never calls a completion model sent no prompt, so its
        # failed result carries none, like its completed result. Input
        # preparation interpolates one for every step and attaches it to what
        # it refuses.
        failed_prompt = (
            typed_exc.effective_prompt if step.may_call_completion_provider else ""
        )
        error_code = typed_io_failure_code(typed_exc.code)
        rejected_completion = (
            typed_exc.rejected_completion
            if isinstance(typed_exc, StepOutputValidationException)
            else None
        )
        run_error_message = build_typed_failure_run_error_message(
            step_order=step.step_order,
            error_code=error_code,
            error_message=str(typed_exc),
            contract_validation=typed_exc.contract_validation,
        )
        if isinstance(typed_exc, StepDeadlineExceeded):
            error_message = str(typed_exc)
            run_error_message = error_message
        elif _tool_step_failed_before_its_input_was_stored(
            step, attempt_no=attempt_no, state=state
        ):
            error_message = str(typed_exc)
        else:
            error_message = _with_provider_work_disclosure(
                str(typed_exc),
                step=step,
                completion_received=rejected_completion is not None,
            )
            run_error_message = _with_provider_work_disclosure(
                run_error_message,
                step=step,
                completion_received=rejected_completion is not None,
            )
        deadline = typed_exc if isinstance(typed_exc, StepDeadlineExceeded) else None
        completed_items, total_items = _failed_item_counts(typed_exc)
        failure_plan = build_typed_failure_plan(
            claimed=claimed,
            error_code=error_code,
            error_message=error_message,
            input_payload_json=failed_input_payload,
            effective_prompt=failed_prompt if isinstance(failed_prompt, str) else None,
            run_error_message=run_error_message,
            rejected_output=rejected_output_of(typed_exc),
            rejected_completion=rejected_completion,
            max_inline_text_bytes=self.max_inline_text_bytes,
            step_phase=deadline.step_phase if deadline is not None else None,
            completed_items=completed_items,
            total_items=total_items,
            provider_work_may_have_completed=(
                deadline.provider_work_may_have_completed
                if deadline is not None
                else None
            ),
            run_error_details=(
                typed_exc.run_error_details
                if isinstance(typed_exc, TranscriptionFailure)
                else FlowRunErrorDetails.from_budget_context(typed_exc.context)
            ),
        )
        await self._rollback()
        attempt_start = _attempt_start_for_step(state=state, step=step)
        evidence = failure_evidence(typed_exc)
        requested_model, provider = (
            (attempt_start.requested_model, attempt_start.provider)
            if attempt_start is not None
            else _pre_attempt_start_model_from_state_cache(state=state, step=step)
        )
        self._attach_pending_transcript_source(failure_plan.failed_result, attempt_no)
        await self.flow_run_repo.finish_attempt(
            run_id=run_id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=tenant_id,
            status=failure_plan.attempt_status,
            error_code=failure_plan.error_code.value,
            error_message=failure_plan.error_message,
            rejected_completion=rejected_completion,
            requested_model=requested_model,
            provider=provider,
            provenance_json=build_incomplete_attempt_provenance(
                rag_metadata=evidence.rag_metadata,
            ),
            attempt_input=build_terminal_attempt_input(
                start=attempt_start,
                resolved_input=(
                    failure_plan.failed_result.input_payload_json
                    if attempt_start is None
                    else None
                ),
            ),
            output_payload_json=failure_plan.failed_result.output_payload_json,
        )
        saved_result = await self.flow_run_repo.save_step_result(
            run_id,
            failure_plan.failed_result,
            tenant_id=tenant_id,
            attempt_no=attempt_no,
        )
        # Terminalization won the race; report the persisted run outcome rather
        # than this step's failure.
        if saved_result is None:
            if (run_id, step.step_id, attempt_no) in self._pending_transcript_sources:
                await self._rollback()
            else:
                await self._commit()
            self._forget_pending_transcript(run_id, step.step_id, attempt_no)
            return await self._return_after_terminalized_step_write(
                run_id=run_id,
                flow_id=claimed.flow_id,
                tenant_id=tenant_id,
            )
        await self._publish_transcript_source(
            run_id=run_id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=tenant_id,
            flow_id=claimed.flow_id,
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
                details=failure_plan.run_error_details,
            ),
        )
        await self._commit()
        self._forget_pending_transcript(run_id, step.step_id, attempt_no)
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
        provider_error_code = _flow_provider_error_code(exc)
        evidence_persistence_error = (
            exc if isinstance(exc, ProviderCallEvidencePersistenceError) else None
        )
        completed_items, total_items = _failed_item_counts(exc)
        run_error_details = FlowRunErrorDetails.from_budget_context(
            {"completed_items": completed_items, "total_items": total_items}
        )
        if evidence_persistence_error is not None:
            run_error_details = (run_error_details or FlowRunErrorDetails()).model_copy(
                update={"provider_call_evidence_gap": evidence_persistence_error.facts}
            )
        late_capability_rejection = (
            isinstance(exc, ProviderCapabilityRejectedException)
            and not exc.retry_without_capability_safe
        )
        if evidence_persistence_error is not None:
            if evidence_persistence_error.facts.call_id is None:
                public_error = (
                    f"Flow step {step.step_order} did not send the current provider "
                    "request because request evidence could not be persisted."
                )
            else:
                public_error = (
                    f"Flow step {step.step_order} failed after provider work because "
                    "provider-call evidence could not be persisted; the call was not "
                    "repeated."
                )
        elif isinstance(exc, ProviderCallObserverError):
            # This request was not sent, but an earlier fallback or tool-round request
            # may already have reached the provider.
            public_error = (
                f"Flow step {step.step_order} did not send the current provider "
                "request because request evidence could not be recorded safely."
            )
        elif isinstance(exc, ProviderRejectedRequestException) and not (
            late_capability_rejection
        ):
            public_error = (
                f"Flow step {step.step_order} execution failed because the provider "
                "rejected the request; the runtime did not repeat it."
            )
        elif provider_error_code is FlowApiErrorCode.PROVIDER_RATE_LIMITED:
            public_error = (
                f"Flow step {step.step_order} was rate-limited by the provider; "
                "wait before starting a new run."
            )
        elif provider_error_code is FlowApiErrorCode.PROVIDER_UNAVAILABLE:
            public_error = _with_provider_work_disclosure(
                f"Flow step {step.step_order} execution failed because the provider "
                "was unavailable.",
                step=step,
            )
        elif isinstance(exc, ToolArgumentCheckFailed):
            # A tool step whose input was never stored asked no provider; any
            # other check may have run after the step's model (an output check
            # always does), so the disclosure owner states what it may have
            # spent. A tool, if any, may have answered.
            public_error = (
                f"Flow step {step.step_order} failed because this worker could not "
                "run its schema check; the step produced no result."
            )
            if not _tool_step_failed_before_its_input_was_stored(
                step, attempt_no=attempt_no, state=state
            ):
                public_error = _with_provider_work_disclosure(public_error, step=step)
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
                else provider_error_code or FlowApiErrorCode.STEP_EXECUTION_FAILED
            ),
        )
        await self._rollback()
        self._attach_pending_transcript_source(failure_plan.failed_result, attempt_no)
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
            provenance_json=build_incomplete_attempt_provenance(
                rag_metadata=failure_evidence(exc).rag_metadata,
            ),
            attempt_input=build_terminal_attempt_input(
                start=attempt_start,
                resolved_input=(
                    failure_plan.failed_result.input_payload_json
                    if attempt_start is None
                    else None
                ),
            ),
            output_payload_json=failure_plan.failed_result.output_payload_json,
        )
        saved_result = await self.flow_run_repo.save_step_result(
            run_id,
            failure_plan.failed_result,
            tenant_id=tenant_id,
            attempt_no=attempt_no,
        )
        # Terminalization won the race; report the persisted run outcome rather
        # than this step's failure.
        if saved_result is None:
            if (run_id, step.step_id, attempt_no) in self._pending_transcript_sources:
                await self._rollback()
            else:
                await self._commit()
            self._forget_pending_transcript(run_id, step.step_id, attempt_no)
            return await self._return_after_terminalized_step_write(
                run_id=run_id,
                flow_id=claimed.flow_id,
                tenant_id=tenant_id,
            )
        await self._publish_transcript_source(
            run_id=run_id,
            step_id=step.step_id,
            attempt_no=attempt_no,
            tenant_id=tenant_id,
            flow_id=claimed.flow_id,
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
                details=_details_after_tool_steps(
                    run_error_details,
                    code=failure_plan.error_code,
                    step=step,
                    state=state,
                ),
            ),
        )
        await self._commit()
        self._forget_pending_transcript(run_id, step.step_id, attempt_no)
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
        attempt_start: FlowStepAttemptStart | None,
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
            provenance_json=build_attempt_provenance(
                output=output,
            ),
            attempt_input=build_terminal_attempt_input(
                start=attempt_start,
                resolved_input=(
                    saved_result.input_payload_json if attempt_start is None else None
                ),
            ),
            output_payload_json=saved_result.output_payload_json,
        )
        if commit:
            await self._commit()
        return saved_result

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

    def _build_step_input_resolution_deps(
        self,
        transcription_call_observer: "ProviderCallObserver | None" = None,
        *,
        attempt_no: int,
        transcript_source_preparation: TranscriptSourcePreparation | None = None,
    ) -> StepInputResolutionDeps:
        return StepInputResolutionDeps(
            apply_output_cap=self._apply_output_cap,
            commit=self._commit,
            end_read_transaction=self._end_read_transaction,
            variable_resolver=self.variable_resolver,
            resolve_http_input_source_text=self._resolve_http_input_source_text,
            resolve_tool_input=partial(self._resolve_tool_input, attempt_no=attempt_no),
            file_service=self.file_service,
            transcribers=self.transcribers,
            flow_repo=self.flow_repo,
            space_repo=self.space_repo,
            flow_run_repo=self.flow_run_repo,
            audit_service=self.audit_service,
            actor=self.runtime_actor,
            max_generic_files=self.max_generic_files,
            input_limits=self.input_limits,
            max_audio_files=self.max_audio_files,
            max_inline_text_bytes=self.max_inline_text_bytes,
            logger=logger,
            transcription_call_observer=transcription_call_observer,
            stage_transcript_source=self._stage_transcript_source,
            stage_run_transcript=self._stage_run_transcript,
            transcript_source_preparation=transcript_source_preparation,
        )

    def _stage_transcript_source(
        self, reference: TranscriptSourceReference, source: TranscriptSourcePreparation
    ) -> None:
        key = (reference.run_id, reference.step_id, reference.attempt_no)
        pending = self._pending_transcript_sources.get(key)
        if pending is not None and pending.preparation is not source:
            raise FlowRuntimeInvariantError(
                "A transcription attempt must share its preparation state."
            )
        self._pending_transcript_sources[key] = _PendingTranscript(
            reference=reference, preparation=source
        )

    def _stage_run_transcript(
        self, reference: TranscriptSourceReference, transcript: InlineTranscript | None
    ) -> None:
        key = (reference.run_id, reference.step_id, reference.attempt_no)
        pending = self._pending_transcript_sources.get(key)
        if pending is None:
            raise FlowRuntimeInvariantError(
                "A run transcript was staged before its transcript source."
            )
        self._pending_transcript_sources[key] = replace(
            pending, run_transcript=transcript
        )

    def _forget_pending_transcript(
        self, run_id: UUID, step_id: UUID, attempt_no: int
    ) -> None:
        self._pending_transcript_sources.pop((run_id, step_id, attempt_no), None)

    def _attach_pending_transcript_source(
        self, result: FlowStepResult, attempt_no: int
    ) -> None:
        pending = self._pending_transcript_sources.get(
            (result.flow_run_id, result.step_id, attempt_no)
        )
        if pending is not None:
            result.input_payload_json = with_transcript_source_reference(
                result.input_payload_json, pending.reference
            )

    async def _publish_transcript_source(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> None:
        from eneo.flows.runtime.transcription_runtime import persist_transcript_words

        pending = self._pending_transcript_sources.get((run_id, step_id, attempt_no))
        if pending is not None:
            await FlowTranscriptSourceRepository(session=self.session).insert(
                tenant_id=tenant_id,
                flow_id=flow_id,
                reference=pending.reference,
                source=pending.preparation.source,
            )
            await persist_transcript_words(
                transcript_words_repo=self.transcript_words_repo,
                run_id=run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
                step_id=step_id,
                preparation=pending.preparation,
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
        transcription_call_observer: "ProviderCallObserver | None" = None,
        prompt_template: str = "",
        step_input_override: StepInputValue | None = None,
        attempt_no: int = 1,
    ) -> StepInputValue:
        pending = self._pending_transcript_sources.get(
            (run.id, step.step_id, attempt_no)
        )
        deps = self._build_step_input_resolution_deps(
            transcription_call_observer,
            attempt_no=attempt_no,
            transcript_source_preparation=(
                pending.preparation if pending is not None else None
            ),
        )
        return await resolve_step_input_runtime(
            attempt_no=attempt_no,
            step=step,
            context=context,
            run=run,
            prior_results=prior_results,
            state=state,
            version_metadata=version_metadata,
            requested_file_ids=requested_file_ids,
            prompt_template=prompt_template,
            step_input_override=step_input_override,
            deps=deps,
        )

    async def _resolve_http_input_source_text(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        context: FlowVariableContext,
    ) -> FlowOutsideInputResolution:
        deps = FlowHttpOrchestrationDeps(
            encryption_service=self.encryption_service,
            variable_resolver=self.variable_resolver,
            resolve_timeout_seconds=self.http_runtime.resolve_timeout_seconds,
            read_response_text=self.http_runtime.read_response_text,
            send_http_request=self.http_runtime.send_request,
            audit_http_outbound=self._audit_http_outbound,
        )
        return await resolve_http_input_source_text_orchestrated(
            step=step,
            run=run,
            context=context,
            deps=deps,
        )

    async def _resolve_tool_input(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        context: FlowVariableContext,
        counted_server_levels: Mapping[int, int | None],
        attempt_no: int,
    ) -> FlowOutsideInputResolution:
        async def record_call(
            *,
            start: FlowStepAttemptToolCallStart,
            result: FlowStepAttemptToolCallResult | None,
        ) -> None:
            try:
                written = await self.flow_run_repo.write_attempt_tool_call_evidence(
                    run_id=run.id,
                    step_id=step.step_id,
                    attempt_no=attempt_no,
                    tenant_id=run.tenant_id,
                    start=start,
                    result=result,
                )
                if written == "attempt_closed":
                    raise FlowStepAttemptClosed(
                        run_id=run.id, step_id=step.step_id, attempt_no=attempt_no
                    )
                await self._commit()
            except (asyncio.CancelledError, Exception):
                # Releases the run and attempt row locks the write took, so
                # no other writer waits on them while the read audits how it
                # ended.
                await self._rollback()
                raise

        return await resolve_tool_input_runtime(
            step=step,
            run=run,
            context=context,
            deps=self._tool_input_deps(),
            space_id=await self._flow_space_id(run),
            counted_server_levels=counted_server_levels,
            record_call=record_call,
        )

    async def _tool_preflight(
        self, steps: list[RuntimeStep], *, run: FlowRun, state: RunExecutionState
    ) -> _ToolPreflight | None:
        """What one preflight of a run with a tool step asks its tools with;
        None for a run without one, which needs neither reader nor space.

        A tool step the run has completed is not asked about again: the level
        its answer was counted at is a recorded fact of the run, read from the
        ``tool_answer`` edge of the attempt that completed it. A run without a
        completed tool step reads none.
        """
        tool_step_orders = [
            step.step_order
            for step in steps
            if FlowInputSource(step.input_source) is FlowInputSource.TOOL
        ]
        if not tool_step_orders:
            return None
        completed = sorted(
            order for order in tool_step_orders if order in state.completed_by_order
        )
        recorded_levels: dict[int, int | None] = {}
        if completed:
            answers = await self.flow_run_repo.list_completed_tool_answers(
                run_id=run.id, tenant_id=run.tenant_id
            )
            recorded_levels = {
                order: answers[order].server_classification_level
                for order in completed
                if order in answers
            }
            without_edge = [
                order for order in completed if order not in recorded_levels
            ]
            if without_edge:
                # A tool step this run completed stored the edge with its
                # read, and one it took over from the run a retry started
                # from got the edge of the attempt it was imported from
                # (FlowRunRepository.seed_validated_prefix): that run read
                # the tool in a version that stores the edge, as every
                # version that runs tool steps does.
                raise FlowRuntimeInvariantError(
                    "A completed tool step has no tool_answer evidence edge "
                    f"(run_id={run.id}, step_orders={without_edge})."
                )
        return _ToolPreflight(
            facts=ToolFactsReadOnce(lambda: self._tool_input_deps().facts_reader),
            space_id=await self._flow_space_id(run),
            recorded_levels=recorded_levels,
        )

    def _tool_input_deps(self) -> ToolInputDeps:
        if self.tool_facts_reader is None or self.tool_caller is None:
            raise FlowRuntimeInvariantError(
                "A run with a tool step needs the tool facts reader and the tool caller."
            )
        return ToolInputDeps(
            facts_reader=self.tool_facts_reader,
            caller=self.tool_caller,
            variable_resolver=self.variable_resolver,
            destination_policy=self.tool_destination_policy,
            name_resolver=self.tool_name_resolver,
            call_timeout_seconds=self.tool_call_timeout_seconds,
            max_inline_text_bytes=self.max_inline_text_bytes,
            audit_http_outbound=self._audit_http_outbound,
        )

    async def _flow_space_id(self, run: FlowRun) -> UUID:
        # Read for the preflight and again for each read: the decision is about
        # the space the flow is in now. A run of a deleted flow may still be
        # finishing.
        space_id = await self.flow_repo.get_space_id(
            flow_id=run.flow_id, tenant_id=run.tenant_id, include_deleted=True
        )
        if space_id is None:
            raise NotFoundException("Flow not found.")
        return space_id

    async def _fail_run_before_its_steps(
        self,
        exc: BadRequestException,
        *,
        run_id: UUID,
        tenant_id: UUID,
        source: FlowRunLifecycleSource,
    ) -> dict[str, Any]:
        run_error = self._run_error_from_bad_request(
            exc, source=source, default_code=FlowApiErrorCode.DEFINITION_INVALID
        )
        await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=source,
            error=run_error,
        )
        await self._commit()
        return {"status": "failed", "error": run_error.code.value}

    async def _refuse_unusable_tools(
        self,
        steps: list[RuntimeStep],
        *,
        run: FlowRun,
        state: RunExecutionState,
        tool_preflight: _ToolPreflight | None,
    ) -> None:
        """Refuse a run with a tool step whose tool a level does not allow for
        the flow's space, or is no longer the tool the flow pinned, before any
        step. The read asks again before its call.

        A step the run has already completed makes no call any more, so a
        resumed run is not refused for it.
        """
        if tool_preflight is None:
            return
        tool_steps = [
            step
            for step in sorted(steps, key=lambda item: item.step_order)
            if FlowInputSource(step.input_source) is FlowInputSource.TOOL
            and step.step_order not in state.completed_by_order
        ]
        for step in tool_steps:
            await read_usable_tool(
                step_order=step.step_order,
                config=pinned_tool_config(step),
                facts_reader=tool_preflight.facts,
                tenant_id=run.tenant_id,
                space_id=tool_preflight.space_id,
            )

    async def _load_assistant(
        self,
        assistant_id: UUID,
        state: RunExecutionState | None = None,
        *,
        snapshot: dict[str, Any] | None = None,
    ) -> RuntimeAssistantProtocol:
        validated = validate_assistant_execution_snapshot(
            snapshot=snapshot, assistant_id=assistant_id
        )
        key = assistant_cache_key(assistant_id, validated)
        if state and key in state.assistant_cache:
            assistant = state.assistant_cache[key]
            self._reject_flow_mcp_assistant(assistant)
            return assistant
        if state is None or state.flow_id is None:
            raise FlowRuntimeInvariantError("Frozen assistants require run context.")
        if state.flow_space is None:
            try:
                flow = await self.flow_repo.get(
                    flow_id=state.flow_id, tenant_id=self.runtime_actor.tenant_id
                )
            except NotFoundException as exc:
                # The run row cascades with its flow row, so the flow is deleted.
                raise _FlowDeletedDuringRun() from exc
            space = await self.space_repo.get_execution_space(flow.space_id)
            if space.tenant_id != self.runtime_actor.tenant_id:
                raise NotFoundException()
            state.flow_space = space
        space = state.flow_space
        if space.id is None:
            raise NotFoundException()
        live = await self.space_repo.get_execution_assistant(
            space_id=space.id, assistant_id=assistant_id
        )
        if live is not None:
            self._reject_flow_mcp_assistant(live)
        assistant = await self._load_frozen_assistant(
            space=space,
            live=live,
            snapshot=AssistantExecutionSnapshotV2.model_validate(validated),
            state=state,
        )
        state.assistant_cache[key] = assistant
        return assistant

    async def _load_frozen_assistant(
        self,
        *,
        space: Space,
        live: Assistant | None,
        snapshot: AssistantExecutionSnapshotV2,
        state: RunExecutionState,
    ) -> Assistant:
        if space.id is None:
            raise NotFoundException()
        binding = snapshot.completion_model
        model = None
        if binding is not None:
            model = await self.space_repo.completion_model_repo.one(
                UUID(binding.model_id)
            )
            if model.tenant_id != self.runtime_actor.tenant_id:
                raise NotFoundException()
            if (
                str(model.id) != binding.model_id
                or str(model.provider_id) != binding.provider_id
                or model.provider_type != binding.provider_type
                or model.get_model_route() != binding.resolved_route
            ):
                raise BadRequestException(
                    "Assistant model binding changed after publication.",
                    code=FlowApiErrorCode.ASSISTANT_SNAPSHOT_DRIFT.value,
                )
            provider = await load_active_litellm_provider(
                session=self.session,
                provider_id=UUID(binding.provider_id),
                tenant_id=self.runtime_actor.tenant_id,
            )
            if (
                str(provider.id) != binding.provider_id
                or provider.provider_type != binding.provider_type
                or model.get_model_route(provider_type=provider.provider_type)
                != binding.resolved_route
            ):
                raise BadRequestException(
                    "Assistant model binding changed after publication.",
                    code=FlowApiErrorCode.ASSISTANT_SNAPSHOT_DRIFT.value,
                )
            model = deepcopy(model)
        collections: list[Collection] = []
        websites: list[Website] = []
        integrations: list[IntegrationKnowledge] = []
        for ref in snapshot.knowledge_refs:
            resource_id = UUID(ref.id)
            if ref.kind == "collection":
                if resource_id not in state.collection_cache:
                    state.collection_cache[
                        resource_id
                    ] = await self.space_repo.get_collection(resource_id)
                collections.append(state.collection_cache[resource_id])
            elif ref.kind == "website":
                if resource_id not in state.website_cache:
                    state.website_cache[
                        resource_id
                    ] = await self.space_repo.get_website(resource_id)
                websites.append(state.website_cache[resource_id])
            else:
                if resource_id not in state.integration_knowledge_cache:
                    state.integration_knowledge_cache[
                        resource_id
                    ] = await self.space_repo.get_integration_knowledge(resource_id)
                integrations.append(state.integration_knowledge_cache[resource_id])
        metadata: list[FileMetadata] = []
        for attachment in snapshot.attachments:
            file = await self.file_repo.get_by_id(
                UUID(attachment.file_id), tenant_id=self.runtime_actor.tenant_id
            )
            if file.tenant_id != self.runtime_actor.tenant_id:
                raise NotFoundException()
            metadata.append(file)
        loaded_files = await self.file_content_loader.load(metadata) if metadata else {}
        attachments: list[File] = []
        for attachment in snapshot.attachments:
            loaded = loaded_files.get(UUID(attachment.file_id))
            if loaded is None or loaded.checksum != attachment.checksum:
                raise BadRequestException(
                    "Assistant snapshot attachment checksum does not match.",
                    code=FlowApiErrorCode.ASSISTANT_SNAPSHOT_RESOURCE_INVALID.value,
                )
            attachments.append(loaded)
        prompt = Prompt(
            id=None,
            created_at=None,
            updated_at=None,
            text=snapshot.instructions or "",
            description=None,
            user_id=live.prompt.user_id
            if live is not None and live.prompt is not None
            else None,
            tenant_id=self.runtime_actor.tenant_id,
            is_selected=True,
            user=None,
        )
        return Assistant(
            id=UUID(snapshot.assistant_id),
            user=live.user if live is not None else None,
            space_id=space.id,
            name=live.name if live is not None else "",
            prompt=prompt,
            completion_model=model,
            completion_model_kwargs=ModelKwargs.model_validate(
                snapshot.completion_model_kwargs.model_dump()
            ),
            logging_enabled=live.logging_enabled if live is not None else False,
            websites=websites,
            collections=collections,
            integration_knowledge_list=integrations,
            attachments=attachments,
            published=True,
            inline_file_text=snapshot.inline_file_text,
            origin=AssistantOrigin(snapshot.origin),
            mcp_servers=[],
        )

    @staticmethod
    def _reject_flow_mcp_assistant(assistant: RuntimeAssistantProtocol) -> None:
        if assistant.mcp_servers:
            raise BadRequestException(
                "Flow MCP is unsupported. Remove MCP servers and tools from the step assistant before running the flow."
            )

    async def _validate_assistant_snapshots(
        self,
        *,
        steps: list[RuntimeStep],
        state: RunExecutionState,
        run_id: UUID,
    ) -> None:
        for step in steps:
            validated_snapshot = validate_assistant_execution_snapshot(
                snapshot=step.assistant_snapshot,
                assistant_id=step.assistant_id,
            )
            try:
                await self._load_assistant(
                    step.assistant_id, state, snapshot=validated_snapshot
                )
            except (
                NotFoundException,
                ProviderNotFoundException,
                ProviderInactiveException,
                ObjectContentIntegrityError,
            ) as exc:
                raise BadRequestException(
                    "Assistant snapshot resource is missing, inaccessible, or inactive.",
                    code=FlowApiErrorCode.ASSISTANT_SNAPSHOT_RESOURCE_INVALID.value,
                    context={"step_order": step.step_order},
                ) from exc

    def _refuse_unacceptable_http_configs(self, steps: list[RuntimeStep]) -> None:
        """Refuse a run whose stored HTTP config the runtime would reject, before any step.

        A stored config is parsed as the request compiler parses it, and its
        timeout is held to the runtime's own cap, so a config the runtime would
        reject after claiming the step fails the run here instead. A credential
        is a literal and the compiler refuses a template in one, but only after
        the step has run; a version published before that rule keeps its
        ciphertext, so it is read decrypted.
        """
        for step in steps:
            configs = sent_step_http_configs(
                step_order=step.step_order,
                input_source=step.input_source,
                output_mode=step.output_mode,
                input_config=step.input_config,
                output_config=step.output_config,
            )
            for label, config in configs:
                self._refuse_timeout_over_the_cap(step, label, config.timeout_seconds)
            for label, fields in templated_step_credentials(
                step_order=step.step_order,
                input_source=step.input_source,
                output_mode=step.output_mode,
                input_config=step.input_config,
                output_config=step.output_config,
                encryption_service=self.encryption_service,
            ):
                raise BadRequestException(
                    credential_template_message(
                        step_order=step.step_order, label=label, fields=fields
                    ),
                    code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
                    context={"step_order": step.step_order},
                )

    async def _refuse_model_steps_without_a_model(
        self, steps: list[RuntimeStep], *, state: RunExecutionState
    ) -> None:
        """Refuse a run with a step that would call a completion model it does
        not have (a version published before publishing checked this), before
        any step, so no earlier step calls its tool or model first."""
        for step in steps:
            assistant = await self._load_assistant(
                step.assistant_id, state, snapshot=step.assistant_snapshot
            )
            require_completion_model_for_step(
                step_order=step.step_order,
                output_mode=step.output_mode,
                has_completion_model=assistant.completion_model is not None,
            )

    def _refuse_timeout_over_the_cap(
        self, step: RuntimeStep, label: str, timeout_seconds: int
    ) -> None:
        try:
            self.http_runtime.resolve_timeout_seconds(
                timeout_seconds, step_order=step.step_order, config_label=label
            )
        except TypedIOValidationException as exc:
            raise BadRequestException(
                str(exc),
                code=exc.code,
                context={
                    "step_order": step.step_order,
                    "field": f"{label}.timeout_seconds",
                },
            ) from None

    async def _resolve_step_output_levels(
        self,
        *,
        steps: list[RuntimeStep],
        state: RunExecutionState,
        run: FlowRun,
        tool_preflight: _ToolPreflight | None,
    ) -> dict[int, int | None]:
        """Every step's effective output level, in order, before any step runs.

        A step's floor depends on the steps before it, so a run that would fail
        this check at step three must not have produced steps one and two.
        """
        levels: dict[int, int | None] = {}
        for step in sorted(steps, key=lambda item: item.step_order):
            levels[step.step_order] = await self._validate_runtime_step_security(
                step=step,
                state=state,
                run=run,
                prior_output_levels_by_order=levels,
                tool_preflight=tool_preflight,
            )
        return levels

    async def _validate_runtime_step_security(
        self,
        *,
        step: RuntimeStep,
        state: RunExecutionState,
        run: FlowRun,
        prior_output_levels_by_order: dict[int, int | None],
        tool_preflight: _ToolPreflight | None,
    ) -> int | None:
        assistant = await self._load_assistant(
            step.assistant_id, state, snapshot=step.assistant_snapshot
        )
        if state.flow_space is None:
            raise FlowRuntimeInvariantError("Frozen assistants require a flow space.")
        space = state.flow_space
        external_source: ExternalSourceClassification | None = None
        if tool_preflight is None:
            # The run has no tool step.
            pass
        elif step.step_order in tool_preflight.recorded_levels:
            # A completed tool step: its answer is the step's stored input at
            # the level it was counted at then, and it sends nothing any more.
            external_source = ExternalSourceClassification(
                level=tool_preflight.recorded_levels[step.step_order],
                sent_step_orders=(),
            )
        else:
            # The server of the step's pinned tool, read for the tenant and
            # the space the tool decision is asked about.
            external_source = await read_tool_source_classification(
                input_source=step.input_source,
                step_order=step.step_order,
                input_config=step.input_config,
                step_ref_mapping=state.step_ref_mapping,
                facts_reader=lambda: tool_preflight.facts,
                tenant_id=run.tenant_id,
                space_id=tool_preflight.space_id,
                security_enabled=self.security_classification_enabled,
            )
            if external_source is not None:
                state.counted_tool_server_levels[step.step_order] = (
                    external_source.level
                )
        evaluation = evaluate_step_security_classification(
            step_order=step.step_order,
            step_id=step.step_id,
            # Preflight runs before any step completes, so the definition
            # boundary (not the completed set) bounds the references.
            upstream_step_orders=resolve_step_upstream_orders(
                input_source=step.input_source,
                step_order=step.step_order,
                input_bindings=step.input_bindings,
                prompt_template=(
                    assistant.get_prompt_text()
                    if flow_output_mode_uses_completion_model(step.output_mode)
                    else None
                ),
                output_mode=step.output_mode,
                input_config=step.input_config,
                output_config=step.output_config,
                step_ref_mapping=state.step_ref_mapping,
                max_prior_step_order=step.step_order - 1,
            ),
            output_mode=step.output_mode,
            output_classification_override=step.output_classification_override,
            prior_output_levels_by_order=prior_output_levels_by_order,
            assistant=assistant,
            space=space,
            security_enabled=self.security_classification_enabled,
            external_source=external_source,
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
        tool: AuditedToolCall | None = None,
    ) -> None:
        try:
            async with self.read_audit_service() as audit_service:
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
                    tool=tool,
                    deps=HttpAuditDeps(
                        audit_service=audit_service,
                        actor=self.runtime_actor,
                        logger=logger,
                    ),
                )
        except Exception:
            # As audit_http_outbound does for the audit log itself: a read is
            # not failed because its audit record could not be queued.
            logger.warning(
                "flow_executor.read_audit_service_failed: the read's audit record "
                "may not have been queued run_id=%s step_order=%d",
                run.id,
                step.step_order,
                exc_info=True,
            )

    async def _process_typed_output(
        self,
        *,
        full_text: str,
        step: RuntimeStep,
        run: FlowRun,
    ) -> TypedOutputProcessingResult:
        from eneo.flows.output_processing import compile_validators, parse_json_output

        deps = OutputRuntimeDeps(
            file_service=self.file_service,
            compile_validators=compile_validators,
            parse_json_output=parse_json_output,
            check_contract=partial(check_contract_in_child, side="output"),
            render_document=self.document_render_service.render_document,
            render_structured_document=(
                self.document_render_service.render_structured_document
            ),
            file_names=self._file_names(),
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
        existing_generated_file_id: UUID | None = None,
    ) -> tuple[str, list[UUID]]:
        """Callers must verify that an existing file contains the same UTF-8 bytes."""
        encoded = text.encode("utf-8")
        if len(encoded) <= self.max_inline_text_bytes:
            return text, []

        file_id = existing_generated_file_id
        if file_id is None:
            file_row = await save_generated_flow_file(
                file_service=self.file_service,
                run=run,
                payload=encoded,
                name=f"flow-{run.id}-step-{step.step_order}-output.txt",
                mimetype="text/plain",
                file_type=FileType.TEXT,
            )
            file_id = file_row.id
        return utf8_prefix(text, max_bytes=self.max_inline_text_bytes), [file_id]

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

    async def _cancel_run_of_deleted_flow(
        self, *, run_id: UUID, tenant_id: UUID, message: str
    ) -> dict[str, Any]:
        await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.CANCELLED,
            source=FlowRunLifecycleSource.FLOW_DELETED,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.FLOW_DELETED,
                code=FlowApiErrorCode.FLOW_DELETED,
                message=message,
            ),
        )
        await self._commit()
        return {"status": "cancelled", "reason": FlowApiErrorCode.FLOW_DELETED.value}

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

    async def _request_webhook_delivery(self, *, run_id: UUID) -> None:
        """Ask for the webhook deliveries this run just committed to be sent now.

        Best-effort, outside any transaction: the outbox cron requests delivery
        every interval once workers and the task broker are available, so a
        request that is refused, has an unknown outcome, fails or outlasts its
        deadline is logged and the run goes on as committed. The interval is a
        cadence, not a delivery bound: a backlog, the job's row cap, slow waves
        and worker or broker outages delay delivery. A request that would
        outlast the run's invocation is cut short, or not sent when no time is
        left. Cancellation propagates."""
        if self.task_enqueuer is None:
            return
        timeout = flow_webhook_delivery_request_timeout_seconds(
            invocation_remaining_seconds=None
            if self.invocation_deadline is None
            else self.invocation_deadline - asyncio.get_running_loop().time()
        )
        if timeout <= 0:
            logger.warning(
                "flow_executor.webhook_delivery_request_skipped run_id=%s",
                run_id,
            )
            return
        try:
            async with asyncio.timeout(timeout):
                result = await self.task_enqueuer.enqueue(
                    flow_webhook_delivery_request()
                )
        except Exception:
            logger.warning(
                "flow_executor.webhook_delivery_request_failed run_id=%s",
                run_id,
                exc_info=True,
            )
            return
        if result.status is not TaskEnqueueStatus.ACCEPTED:
            logger.warning(
                "flow_executor.webhook_delivery_request_not_accepted run_id=%s status=%s",
                run_id,
                result.status.value,
            )

    async def _end_read_transaction(self) -> None:
        """End the session's transaction before outside work, if it only read.

        A provider call or an audio download can last minutes, and an idle
        transaction keeps its connection checked out and its snapshot held for
        all of that time. A transaction that has written (or locked a row) is
        left open: what a step writes before its attempt is activated stays
        uncommitted, so a failure before activation still rolls it back.

        The next transaction is begun at once, so a writer that joins an
        ambient transaction (and commits its own only when there is none)
        still writes inside the step's. Beginning is lazy: it takes no
        connection or snapshot until the next statement.

        The rows the session holds are not expired: the step reads rows it
        loaded before the call after it, and an expired attribute cannot be
        loaded lazily under asyncio. Nothing was written, and under READ
        COMMITTED a held row could already be older than a later statement
        inside one transaction, so keeping them changes nothing.
        """
        if self._transaction_writes.only_read():
            sync_session = self.session.sync_session
            expire_on_commit = sync_session.expire_on_commit
            sync_session.expire_on_commit = False
            try:
                await self._commit()
            finally:
                sync_session.expire_on_commit = expire_on_commit
            await self.session.begin()

    async def _rollback(self) -> None:
        await self.session.rollback()
