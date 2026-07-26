from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Final, Literal, Protocol, Sequence, cast
from uuid import UUID

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.completion_models.domain.provider_call_observer import (
    ProviderCallObserver,
    ProviderCallReason,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.completion_models.infrastructure.context_builder import (
    ContextWindowExceededError,
    count_tokens,
)
from eneo.completion_models.infrastructure.tenant_model_capabilities import (
    get_supported_openai_params,
)
from eneo.files.file_models import File
from eneo.flows.citation_sidecar import (
    CITATION_MODE_INLINE_INREF_SIDECAR,
    CITATION_MODE_OFF,
    build_citation_sidecar,
    resolve_citation_mode,
    strip_inline_reference_tags,
)
from eneo.flows.domain.flow import FlowRun, FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
)
from eneo.flows.domain.step_output import (
    OUTPUT_TEXT_OVERFLOW_KEY,
    build_text_overflow_metadata,
)
from eneo.flows.enums import FlowOutputMode, FlowOutputType
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_capability_manifest import is_citation_capable_step
from eneo.flows.flow_run_provenance import MappedProviderCallProvenance
from eneo.flows.runtime.inherited_citations import (
    build_inherited_citation_prompt_appendix,
    collect_inherited_citation_context,
)
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.runtime.output_formats.base import append_output_format_instructions
from eneo.flows.runtime.output_runtime import TypedOutputProcessingResult
from eneo.flows.runtime.protocols import RuntimeAssistantProtocol
from eneo.flows.runtime.rag_retrieval import RAG_RETRIEVAL_FAIL_CLOSED_STATUSES
from eneo.flows.runtime.step_input_resolution import (
    RUNTIME_INPUT_SOURCE_EMPTY_TEXT_DIAGNOSTIC_CODE,
    enforce_inline_input_cap,
)
from eneo.flows.runtime.step_input_validation import (
    validate_input_contract,
    validate_runtime_input_policy,
)
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from eneo.main.exceptions import (
    ProviderCapabilityRejectedException,
    TypedIOValidationException,
)


def _string_key_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    raw_dict = cast(dict[object, Any], value)
    return {str(key): item for key, item in raw_dict.items()}


logger = logging.getLogger(__name__)
LLM_TASK_CANCELLATION_GRACE_SECONDS: Final[float] = 2.0
RAG_RETRIEVAL_QUERY_CHAR_LIMIT: Final[int] = 2048

RagQueryDerivationStrategy = Literal[
    "empty_input",
    "input_text",
    "step_description_only",
    "step_description_with_input_excerpt",
]


@dataclass(frozen=True, slots=True)
class RagQueryDerivation:
    query: str
    strategy: RagQueryDerivationStrategy
    input_truncated: bool

    def to_metadata(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "input_truncated": self.input_truncated,
            "query_length": len(self.query),
        }


def derive_rag_retrieval_query(
    *,
    step: RuntimeStep,
    input_text: str,
) -> RagQueryDerivation:
    input_body = input_text.strip()
    if not input_body:
        return RagQueryDerivation(
            query="",
            strategy="empty_input",
            input_truncated=False,
        )

    step_description = (step.user_description or "").strip()
    if not step_description:
        query = input_body[:RAG_RETRIEVAL_QUERY_CHAR_LIMIT]
        return RagQueryDerivation(
            query=query,
            strategy="input_text",
            input_truncated=len(input_body) > len(query),
        )

    separator = "\n\nInput excerpt:\n"
    available_for_input = (
        RAG_RETRIEVAL_QUERY_CHAR_LIMIT - len(step_description) - len(separator)
    )
    if available_for_input <= 0:
        query = step_description[:RAG_RETRIEVAL_QUERY_CHAR_LIMIT]
        return RagQueryDerivation(
            query=query,
            strategy="step_description_only",
            input_truncated=True,
        )

    input_excerpt = input_body[:available_for_input]
    query = f"{step_description}{separator}{input_excerpt}"
    return RagQueryDerivation(
        query=query,
        strategy="step_description_with_input_excerpt",
        input_truncated=len(input_body) > len(input_excerpt),
    )


class VariableResolverProtocol(Protocol):
    def build_context(
        self,
        flow_input: dict[str, Any] | None,
        prior_results: list[FlowStepResult],
        *,
        current_step_order: int | None = None,
        step_names_by_order: dict[int, str] | None = None,
        step_ref_mapping: dict[str, int] | None = None,
        current_step_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def interpolate(self, template: str, context: dict[str, Any]) -> str: ...


class LoadAssistantFn(Protocol):
    def __call__(
        self,
        assistant_id: UUID,
        state: RunExecutionState | None = None,
    ) -> Awaitable[RuntimeAssistantProtocol]: ...


class ResolveStepInputFn(Protocol):
    def __call__(
        self,
        *,
        step: RuntimeStep,
        context: dict[str, Any],
        run: FlowRun,
        prior_results: list[FlowStepResult],
        state: RunExecutionState,
        version_metadata: dict[str, Any] | None,
        requested_file_ids: Sequence[UUID],
    ) -> Awaitable[StepInputValue]: ...


class RetrieveRagChunksFn(Protocol):
    def __call__(
        self,
        *,
        assistant: RuntimeAssistantProtocol,
        question: str,
        run_id: UUID,
        step_order: int,
    ) -> Awaitable[
        tuple[
            list[InfoBlobChunkInDBWithScore],
            dict[str, Any] | None,
            list[StepDiagnostic],
        ]
    ]: ...


class ProcessTypedOutputFn(Protocol):
    def __call__(
        self,
        *,
        full_text: str,
        step: RuntimeStep,
        run: FlowRun,
    ) -> Awaitable[TypedOutputProcessingResult]: ...


class ApplyOutputCapFn(Protocol):
    def __call__(
        self,
        *,
        text: str,
        run: FlowRun,
        step: RuntimeStep,
    ) -> Awaitable[tuple[str, list[UUID]]]: ...


class RunCancelledFn(Protocol):
    def __call__(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> Awaitable[bool]: ...


class BuildProviderCallObserverFn(Protocol):
    def __call__(
        self,
        mapped_call: MappedProviderCallProvenance | None,
    ) -> ProviderCallObserver: ...


class FlowStepCancelledError(Exception):
    pass


@dataclass
class PreparedStepExecution:
    assistant: RuntimeAssistantProtocol
    step_input: StepInputValue
    effective_prompt: str
    input_payload_for_result: dict[str, Any]
    contract_validation: dict[str, Any] | None
    diagnostics: list[StepDiagnostic]
    llm_files: list[File]


@dataclass(frozen=True)
class StepExecutionRuntimeDeps:
    variable_resolver: VariableResolverProtocol
    completion_service: CompletionService
    load_assistant: LoadAssistantFn
    resolve_step_input: ResolveStepInputFn
    retrieve_rag_chunks: RetrieveRagChunksFn
    process_typed_output: ProcessTypedOutputFn
    apply_output_cap: ApplyOutputCapFn
    max_inline_text_bytes: int | None = None
    logger: logging.Logger | None = None
    llm_request_timeout_seconds: float = 600
    run_cancelled: RunCancelledFn | None = None
    run_cancel_poll_interval_seconds: float = 2.0
    llm_task_cancellation_grace_seconds: float = LLM_TASK_CANCELLATION_GRACE_SECONDS
    rag_retrieval_timeout_seconds: float = 30
    build_provider_call_observer: BuildProviderCallObserverFn | None = None
    mapped_call_context: MappedProviderCallProvenance | None = None


def _resolve_litellm_model_name(assistant: RuntimeAssistantProtocol) -> str | None:
    completion_model = assistant.completion_model
    if completion_model is None:
        return None

    explicit_name = getattr(completion_model, "litellm_model_name", None)
    if isinstance(explicit_name, str) and explicit_name.strip():
        return explicit_name.strip()

    provider = completion_model.provider_type
    name = completion_model.name
    if provider and provider.strip() and name and name.strip():
        return f"{provider.strip()}/{name.strip()}"
    return None


def detect_native_json_output_support(
    assistant: RuntimeAssistantProtocol,
) -> bool | None:
    """
    Return whether LiteLLM reports native response_format support for this model.

    None means capability could not be determined, so callers should preserve the
    previous optimistic behavior instead of tightening compatibility.
    """
    litellm_model_name = _resolve_litellm_model_name(assistant)
    if not litellm_model_name:
        return None

    try:
        supported = get_supported_openai_params(model=litellm_model_name)
    except Exception:
        logger.warning(
            "Failed to detect native JSON output support for flow step execution.",
            extra={"litellm_model_name": litellm_model_name},
            exc_info=True,
        )
        return None

    if not supported:
        return None

    return "response_format" in supported


def json_mode_cache_key(assistant: RuntimeAssistantProtocol) -> str:
    cm = assistant.completion_model
    if cm is None:
        return "unknown:unknown:none"
    provider = cm.provider_type or "unknown"
    name = cm.name or "unknown"
    mid = str(cm.id) if cm.id else "none"
    return f"{provider}:{name}:{mid}"


@dataclass(frozen=True, slots=True)
class JsonResponseFormatPlan:
    native_json_object_attempted: bool
    fallback_call_possible: bool
    strip_stored_response_format: bool


def resolve_json_response_format_plan(
    *,
    step: RuntimeStep,
    assistant: RuntimeAssistantProtocol,
    state: RunExecutionState,
) -> JsonResponseFormatPlan:
    requested = resolve_format_spec(
        step.output_type
    ).should_request_native_json_object_mode(step.output_contract)
    if not requested:
        # Other output modes preserve authored response-format kwargs and the
        # existing no-fallback behavior.
        return JsonResponseFormatPlan(
            native_json_object_attempted=False,
            fallback_call_possible=False,
            strip_stored_response_format=False,
        )

    cache_key = json_mode_cache_key(assistant)
    cached_support = state.json_mode_supported.get(cache_key)
    if cached_support is None:
        detected_support = detect_native_json_output_support(assistant)
        if detected_support is not None:
            state.json_mode_supported[cache_key] = detected_support
            cached_support = detected_support
    native_json_object_attempted = cached_support is not False
    stored_response_format_present = (
        assistant.completion_model_kwargs.response_format is not None
    )
    return JsonResponseFormatPlan(
        native_json_object_attempted=native_json_object_attempted,
        fallback_call_possible=native_json_object_attempted,
        strip_stored_response_format=(
            cached_support is False and stored_response_format_present
        ),
    )


def attach_typed_failure_context(
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
        setattr(exc, "input_payload_json", payload)
    existing_prompt = getattr(exc, "effective_prompt", None)
    if not isinstance(existing_prompt, str):
        setattr(exc, "effective_prompt", effective_prompt)
    return exc


def _context_window_source_hint(input_payload: dict[str, Any]) -> str:
    runtime_input = _string_key_dict(input_payload.get("runtime_input"))
    if not runtime_input:
        return ""
    files = runtime_input.get("files")
    if not isinstance(files, list) or not files:
        return ""
    first_file = _string_key_dict(cast(list[object], files)[0])
    if not first_file:
        return ""
    name = first_file.get("name")
    if isinstance(name, str) and name.strip():
        return f" for source '{name.strip()}'"
    return ""


def _typed_context_window_error(
    exc: ContextWindowExceededError,
    *,
    step: RuntimeStep,
    prepared: PreparedStepExecution,
    deps: StepExecutionRuntimeDeps,
    effective_prompt: str,
) -> TypedIOValidationException:
    source_hint = _context_window_source_hint(prepared.input_payload_for_result)
    if deps.logger is not None:
        deps.logger.warning(
            "flow_executor.context_window_exceeded step_order=%d estimated_tokens=%d max_tokens=%d",
            step.step_order,
            exc.estimated_tokens,
            exc.max_tokens,
        )
    return attach_typed_failure_context(
        TypedIOValidationException(
            f"Step {step.step_order}: packaged model input{source_hint} uses "
            f"about {exc.estimated_tokens} tokens, exceeding the selected "
            f"model window of {exc.max_tokens} tokens. Use a larger-context "
            "model, split the document, or reduce the step input.",
            code=FlowApiErrorCode.TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW.value,
        ),
        input_payload_for_result=prepared.input_payload_for_result,
        effective_prompt=effective_prompt,
    )


async def call_assistant_with_timeout(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    prepared: PreparedStepExecution,
    deps: StepExecutionRuntimeDeps,
    model_kwargs: Any,
    info_blob_chunks: list[InfoBlobChunkInDBWithScore],
    prompt_override: str,
    version: int,
    provider_call_reason: ProviderCallReason,
    step_deadline_monotonic: float | None = None,
) -> Any:
    # When a step deadline is supplied, the json-mode rejection retry shares
    # the same wall-clock budget as the initial call. Without this, a step
    # that consumes most of its timeout on the first attempt is granted a
    # fresh per-call budget for the fallback retry, silently doubling the
    # bound the executor's outer asyncio.wait_for is supposed to enforce.
    loop = asyncio.get_event_loop()
    if step_deadline_monotonic is None:
        timeout = deps.llm_request_timeout_seconds
    else:
        timeout = max(0.0, step_deadline_monotonic - loop.time())

    if timeout <= 0:
        if deps.logger is not None:
            deps.logger.warning(
                "flow_executor.llm_timeout run_id=%s step_order=%d timeout=%s",
                run.id,
                step.step_order,
                deps.llm_request_timeout_seconds,
            )
        raise attach_typed_failure_context(
            TypedIOValidationException(
                f"Step {step.step_order}: LLM request exceeded "
                f"{deps.llm_request_timeout_seconds:g}s timeout.",
                code=FlowApiErrorCode.LLM_REQUEST_TIMEOUT.value,
            ),
            input_payload_for_result=prepared.input_payload_for_result,
            effective_prompt=prepared.effective_prompt,
        )

    llm_task: asyncio.Task[Any] = asyncio.create_task(
        prepared.assistant.get_response(
            question=prepared.step_input.text,
            completion_service=deps.completion_service,
            model_kwargs=model_kwargs,
            files=prepared.llm_files,
            info_blob_chunks=info_blob_chunks,
            stream=False,
            prompt_override=prompt_override,
            version=version,
            reject_context_over_limit=True,
            provider_call_observer=(
                deps.build_provider_call_observer(deps.mapped_call_context)
                if deps.build_provider_call_observer is not None
                else None
            ),
            provider_call_reason=provider_call_reason,
        )
    )
    state.in_flight_llm_task = llm_task

    def _consume_abandoned_llm_task(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            if deps.logger is not None:
                deps.logger.warning(
                    "flow_executor.abandoned_llm_task_failed run_id=%s step_order=%d",
                    run.id,
                    step.step_order,
                    exc_info=True,
                )

    async def _cancel_llm_task_with_grace() -> None:
        if llm_task.done():
            return
        llm_task.cancel()
        grace_seconds = max(0.0, deps.llm_task_cancellation_grace_seconds)
        if grace_seconds <= 0:
            llm_task.add_done_callback(_consume_abandoned_llm_task)
            return
        try:
            await asyncio.wait_for(asyncio.shield(llm_task), timeout=grace_seconds)
        except asyncio.CancelledError:
            return
        except TimeoutError:
            llm_task.add_done_callback(_consume_abandoned_llm_task)
        except Exception:
            if deps.logger is not None:
                deps.logger.warning(
                    "flow_executor.llm_task_failed_after_cancel run_id=%s step_order=%d",
                    run.id,
                    step.step_order,
                    exc_info=True,
                )

    async def _cancel_when_run_cancelled() -> bool:
        if deps.run_cancelled is None:
            return False
        poll_interval = max(0.05, deps.run_cancel_poll_interval_seconds)
        while not llm_task.done():
            await asyncio.sleep(poll_interval)
            try:
                cancelled = await deps.run_cancelled(
                    run_id=run.id,
                    flow_id=run.flow_id,
                    tenant_id=run.tenant_id,
                )
            except Exception:
                if deps.logger is not None:
                    deps.logger.warning(
                        "flow_executor.cancel_watch_failed run_id=%s step_order=%d",
                        run.id,
                        step.step_order,
                        exc_info=True,
                    )
                return False
            if cancelled:
                return True
        return False

    cancel_watcher = (
        asyncio.create_task(_cancel_when_run_cancelled())
        if deps.run_cancelled is not None
        else None
    )
    try:
        while True:
            if step_deadline_monotonic is None:
                wait_timeout = timeout
            else:
                wait_timeout = max(0.0, step_deadline_monotonic - loop.time())
            if wait_timeout <= 0:
                await _cancel_llm_task_with_grace()
                if deps.logger is not None:
                    deps.logger.warning(
                        "flow_executor.llm_timeout run_id=%s step_order=%d timeout=%s",
                        run.id,
                        step.step_order,
                        deps.llm_request_timeout_seconds,
                    )
                raise attach_typed_failure_context(
                    TypedIOValidationException(
                        f"Step {step.step_order}: LLM request exceeded "
                        f"{deps.llm_request_timeout_seconds:g}s timeout.",
                        code=FlowApiErrorCode.LLM_REQUEST_TIMEOUT.value,
                    ),
                    input_payload_for_result=prepared.input_payload_for_result,
                    effective_prompt=prepared.effective_prompt,
                )

            wait_tasks: set[asyncio.Task[Any]] = {llm_task}
            if cancel_watcher is not None:
                wait_tasks.add(cancel_watcher)
            done, _ = await asyncio.wait(
                wait_tasks,
                timeout=wait_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                await _cancel_llm_task_with_grace()
                if deps.logger is not None:
                    deps.logger.warning(
                        "flow_executor.llm_timeout run_id=%s step_order=%d timeout=%s",
                        run.id,
                        step.step_order,
                        deps.llm_request_timeout_seconds,
                    )
                raise attach_typed_failure_context(
                    TypedIOValidationException(
                        f"Step {step.step_order}: LLM request exceeded "
                        f"{deps.llm_request_timeout_seconds:g}s timeout.",
                        code=FlowApiErrorCode.LLM_REQUEST_TIMEOUT.value,
                    ),
                    input_payload_for_result=prepared.input_payload_for_result,
                    effective_prompt=prepared.effective_prompt,
                )
            if llm_task in done:
                try:
                    return llm_task.result()
                except ContextWindowExceededError as exc:
                    raise _typed_context_window_error(
                        exc,
                        step=step,
                        prepared=prepared,
                        deps=deps,
                        effective_prompt=prompt_override,
                    ) from exc
            if cancel_watcher is not None and cancel_watcher in done:
                if cancel_watcher.result():
                    await _cancel_llm_task_with_grace()
                    raise FlowStepCancelledError(
                        "Run was cancelled during step execution."
                    )
                cancel_watcher = None
    except asyncio.CancelledError:
        await _cancel_llm_task_with_grace()
        raise
    except TimeoutError as exc:
        await _cancel_llm_task_with_grace()
        if deps.logger is not None:
            deps.logger.warning(
                "flow_executor.llm_timeout run_id=%s step_order=%d timeout=%s",
                run.id,
                step.step_order,
                deps.llm_request_timeout_seconds,
            )
        raise attach_typed_failure_context(
            TypedIOValidationException(
                f"Step {step.step_order}: LLM request exceeded "
                f"{deps.llm_request_timeout_seconds:g}s timeout.",
                code=FlowApiErrorCode.LLM_REQUEST_TIMEOUT.value,
            ),
            input_payload_for_result=prepared.input_payload_for_result,
            effective_prompt=prepared.effective_prompt,
        ) from exc
    finally:
        if cancel_watcher is not None:
            cancel_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_watcher
        if state.in_flight_llm_task is llm_task:
            state.in_flight_llm_task = None


def build_output_payload(output: StepExecutionOutput) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": output.persisted_text,
    }
    if output.structured_output is not None:
        payload["structured"] = output.structured_output
    if output.output_payload_extensions:
        payload.update(output.output_payload_extensions)
    if output.generated_file_ids:
        payload[OUTPUT_TEXT_OVERFLOW_KEY] = build_text_overflow_metadata(
            file_ids=output.generated_file_ids,
            preview=output.persisted_text,
            full_text=output.full_text,
        )
    return payload


def effective_model_parameters(assistant: RuntimeAssistantProtocol) -> dict[str, Any]:
    kwargs = assistant.completion_model_kwargs.model_dump(exclude_none=False)
    completion_model = assistant.completion_model
    parameter_semantics = {
        key: {"mode": "configured" if kwargs.get(key) is not None else "model_default"}
        for key in ("temperature", "top_p", "reasoning_effort", "verbosity")
    }
    return {
        "model_id": str(completion_model.id)
        if completion_model and completion_model.id
        else None,
        "model_name": completion_model.name if completion_model else None,
        "provider": completion_model.provider_type if completion_model else None,
        **kwargs,
        "parameter_semantics": parameter_semantics,
    }


def apply_prompt_context_trace(
    rag_metadata: dict[str, Any] | None,
    *,
    knowledge_trace: Any,
) -> dict[str, Any] | None:
    if not isinstance(rag_metadata, dict) or knowledge_trace is None:
        return rag_metadata

    if hasattr(knowledge_trace, "model_dump"):
        trace_payload = _string_key_dict(knowledge_trace.model_dump(mode="json"))
    elif isinstance(knowledge_trace, dict):
        trace_payload = _string_key_dict(cast(object, knowledge_trace))
    else:
        return rag_metadata

    payload = dict(rag_metadata)
    tracking = payload.get("tracking")
    if not isinstance(tracking, dict):
        tracking = {}
    tracking = _string_key_dict(cast(object, tracking))
    tracking["prompt_context_inclusion_tracked"] = True
    tracking_note = tracking.get("note")
    if not isinstance(tracking_note, str) or "citations" not in tracking_note:
        tracking["note"] = (
            "References record retrieved candidates and exact prompt inclusion. "
            "Citations and material influence are not currently tracked."
        )
    payload["tracking"] = tracking

    included_source_ids = [
        str(source_id)
        for source_id in cast(list[Any], trace_payload.get("included_source_ids", []))
        if source_id is not None
    ]
    included_source_titles = list(
        dict.fromkeys(
            source_title.strip()
            for group in cast(list[Any], trace_payload.get("included_groups", []))
            if isinstance(group, dict)
            and isinstance(
                (
                    source_title := _string_key_dict(cast(object, group)).get(
                        "source_title"
                    )
                ),
                str,
            )
            and source_title.strip()
        )
    )
    payload["prompt_context"] = {
        "tracked": True,
        "version": trace_payload.get("version"),
        "selection_basis": trace_payload.get("selection_basis"),
        "raw_source_count": trace_payload.get("raw_source_count"),
        "raw_chunk_count": trace_payload.get("raw_chunk_count"),
        "included_source_count": trace_payload.get("included_source_count"),
        "not_included_source_count": trace_payload.get("not_included_source_count"),
        "included_chunk_count": trace_payload.get("included_chunk_count"),
        "knowledge_tokens": trace_payload.get("knowledge_tokens"),
        "truncated_by_token_budget": trace_payload.get("truncated_by_token_budget"),
        "included_source_ids": included_source_ids,
        "not_included_source_ids": cast(
            list[Any], trace_payload.get("not_included_source_ids", [])
        ),
        "included_source_titles": included_source_titles,
        "included_groups": cast(list[Any], trace_payload.get("included_groups", [])),
    }

    references = payload.get("references")
    if isinstance(references, list):
        normalized_references: list[Any] = []
        included_source_ids_set = set(included_source_ids)
        for reference in cast(list[Any], references):
            if not isinstance(reference, dict):
                normalized_references.append(reference)
                continue
            normalized_reference = _string_key_dict(cast(object, reference))
            if str(normalized_reference.get("id")) in included_source_ids_set:
                normalized_reference["usage_state"] = "inserted_into_prompt"
            normalized_references.append(normalized_reference)
        payload["references"] = normalized_references
    return payload


def requested_model_name(assistant: RuntimeAssistantProtocol) -> str | None:
    completion_model = assistant.completion_model
    if completion_model is None:
        return None
    return completion_model.name or None


def citation_mode_for_step(step: RuntimeStep) -> str:
    citation_mode = resolve_citation_mode(step.output_config)
    if citation_mode != CITATION_MODE_INLINE_INREF_SIDECAR:
        return citation_mode
    try:
        output_type = FlowOutputType(step.output_type)
    except ValueError:
        return CITATION_MODE_OFF
    if output_type is not FlowOutputType.TEXT:
        return CITATION_MODE_OFF
    try:
        output_mode = FlowOutputMode(step.output_mode)
    except ValueError:
        return citation_mode
    if is_citation_capable_step(
        output_type=output_type,
        output_mode=output_mode,
        output_config=step.output_config,
    ):
        return citation_mode
    return CITATION_MODE_OFF


def build_runtime_citation_sidecar(
    *,
    raw_completion_text: str,
    rag_metadata: dict[str, Any] | None,
    citation_mode: str,
    inherited_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if citation_mode != CITATION_MODE_INLINE_INREF_SIDECAR:
        return None
    references = (
        rag_metadata.get("references") if isinstance(rag_metadata, dict) else None
    )
    prompt_context = (
        rag_metadata.get("prompt_context") if isinstance(rag_metadata, dict) else None
    )
    prompt_context_dict = (
        _string_key_dict(cast(object, prompt_context))
        if isinstance(prompt_context, dict)
        else None
    )
    inherited_context_dict = (
        inherited_context if isinstance(inherited_context, dict) else None
    )
    included_source_ids = (
        cast(list[str], prompt_context_dict.get("included_source_ids"))
        if prompt_context_dict is not None
        and isinstance(prompt_context_dict.get("included_source_ids"), list)
        else None
    )
    inherited_references = (
        cast(list[dict[str, Any]], inherited_context_dict.get("available_sources"))
        if inherited_context_dict is not None
        and isinstance(inherited_context_dict.get("available_sources"), list)
        else None
    )
    inherited_source_ids = (
        cast(list[str], inherited_context_dict.get("available_source_ids"))
        if inherited_context_dict is not None
        and isinstance(inherited_context_dict.get("available_source_ids"), list)
        else None
    )
    return build_citation_sidecar(
        raw_completion_text,
        references=cast(list[dict[str, Any]], references)
        if isinstance(references, list)
        else None,
        included_source_ids=included_source_ids,
        inherited_references=inherited_references,
        inherited_source_ids=inherited_source_ids,
        citation_mode_requested=True,
        upstream_grounded_step_orders=(
            inherited_context_dict.get("upstream_step_orders")
            if inherited_context_dict is not None
            else None
        ),
        upstream_grounded_step_labels=(
            inherited_context_dict.get("upstream_step_labels")
            if inherited_context_dict is not None
            else None
        ),
        raw_completion_text=raw_completion_text,
    )


def apply_citation_tracking(
    rag_metadata: dict[str, Any] | None,
    *,
    citation_mode: str,
) -> dict[str, Any] | None:
    if citation_mode != CITATION_MODE_INLINE_INREF_SIDECAR or not isinstance(
        rag_metadata, dict
    ):
        return rag_metadata
    payload = dict(rag_metadata)
    tracking = payload.get("tracking")
    if not isinstance(tracking, dict):
        tracking = {}
    tracking = _string_key_dict(cast(object, tracking))
    tracking["citation_tracked"] = True
    tracking["note"] = (
        "References record retrieved candidates, exact prompt inclusion, and explicit inline "
        "citations when citation mode is enabled. Material influence is not currently tracked."
    )
    payload["tracking"] = tracking
    return payload


def infer_finish_reason(
    *,
    completion: Completion | str | Any,
    tool_calls: list[dict[str, Any]] | None,
) -> str | None:
    if isinstance(completion, Completion):
        if completion.stop:
            return "stop"
        if tool_calls:
            return "tool_calls"
    return None


def execution_hash(
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


async def prepare_step_execution(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    version_metadata: dict[str, Any] | None,
    requested_file_ids: Sequence[UUID],
    deps: StepExecutionRuntimeDeps,
    step_input_override: StepInputValue | None = None,
) -> PreparedStepExecution:
    context_results = [
        item
        for item in state.prior_results
        if item.status == FlowStepResultStatus.COMPLETED
    ]
    context = deps.variable_resolver.build_context(
        run.input_payload_json,
        context_results,
        current_step_order=step.step_order,
        step_names_by_order=state.step_names_by_order,
        step_ref_mapping=state.step_ref_mapping,
    )
    assistant = await deps.load_assistant(step.assistant_id, state)
    prompt_text = assistant.get_prompt_text()
    effective_prompt = ""
    input_payload_for_result: dict[str, Any] = {
        "text": "",
        "source_text": "",
        "input_source": step.input_source,
        "used_question_binding": False,
    }
    if step_input_override is None:
        try:
            step_input = await deps.resolve_step_input(
                step=step,
                context=context,
                run=run,
                prior_results=state.prior_results,
                state=state,
                version_metadata=version_metadata,
                requested_file_ids=requested_file_ids,
            )
        except TypedIOValidationException as exc:
            raise attach_typed_failure_context(
                exc,
                input_payload_for_result=input_payload_for_result,
                effective_prompt=effective_prompt,
            ) from exc
    else:
        step_input = step_input_override

    input_payload_for_result.update(
        {
            "text": step_input.text,
            "source_text": step_input.source_text,
            "input_source": step_input.input_source,
            "used_question_binding": step_input.used_question_binding,
        }
    )
    if step_input.transcription_metadata is not None:
        input_payload_for_result["transcription"] = step_input.transcription_metadata
    if step_input.runtime_input_metadata is not None:
        input_payload_for_result["runtime_input"] = step_input.runtime_input_metadata

    if deps.logger is not None:
        deps.logger.info(
            "flow_executor.input_resolved run_id=%s step_order=%d has_files=%s has_structured=%s text_len=%d",
            run.id,
            step.step_order,
            step_input.files is not None and len(step_input.files) > 0,
            step_input.structured is not None,
            len(step_input.text),
        )

    try:
        policy = validate_runtime_input_policy(
            step_order=step.step_order,
            input_type=step.input_type,
            input_source=step.input_source,
            raw_extracted_text=step_input.raw_extracted_text,
            files=step_input.files,
        )
    except TypedIOValidationException as exc:
        raise attach_typed_failure_context(
            exc,
            input_payload_for_result=input_payload_for_result,
            effective_prompt=effective_prompt,
        ) from exc

    prompt_context = deps.variable_resolver.build_context(
        run.input_payload_json,
        context_results,
        current_step_order=step.step_order,
        step_names_by_order=state.step_names_by_order,
        step_ref_mapping=state.step_ref_mapping,
        current_step_input=step_input.runtime_input_metadata,
    )
    effective_prompt = (
        deps.variable_resolver.interpolate(prompt_text, prompt_context)
        if prompt_text
        else ""
    )
    output_format_spec = resolve_format_spec(step.output_type)
    effective_prompt = append_output_format_instructions(
        effective_prompt,
        output_format_spec.prompt_instructions(step.output_contract),
    )
    diagnostics = list(step_input.diagnostics)

    try:
        if deps.max_inline_text_bytes is not None:
            enforce_inline_input_cap(
                step_order=step.step_order,
                input_source=step_input.input_source,
                text=effective_prompt + step_input.text,
                max_inline_text_bytes=deps.max_inline_text_bytes,
            )
        contract_validation = validate_input_contract(
            step_order=step.step_order,
            input_type=step.input_type,
            input_contract=step.input_contract,
            text=step_input.text,
            structured=step_input.structured,
            binding_context=(
                "input_bindings" if step_input.used_question_binding else None
            ),
        )
    except TypedIOValidationException as exc:
        contract_validation_payload = getattr(exc, "contract_validation", None)
        if isinstance(contract_validation_payload, dict):
            input_payload_for_result["contract_validation"] = (
                contract_validation_payload
            )
        raise attach_typed_failure_context(
            exc,
            input_payload_for_result=input_payload_for_result,
            effective_prompt=effective_prompt,
        ) from exc

    if contract_validation is not None:
        input_payload_for_result["contract_validation"] = contract_validation
        if deps.logger is not None:
            deps.logger.info(
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

    llm_files: list[File] = []
    if policy is not None and policy.channel == "files_only":
        llm_files = step_input.files or []

    return PreparedStepExecution(
        assistant=assistant,
        step_input=step_input,
        effective_prompt=effective_prompt,
        input_payload_for_result=input_payload_for_result,
        contract_validation=contract_validation,
        diagnostics=diagnostics,
        llm_files=llm_files,
    )


def _completion_prompt_override(
    *,
    prepared: PreparedStepExecution,
    citation_mode: str,
    inherited_citation_context: dict[str, Any] | None,
) -> str:
    prompt_override = prepared.effective_prompt
    if citation_mode == CITATION_MODE_INLINE_INREF_SIDECAR:
        inherited_appendix = build_inherited_citation_prompt_appendix(
            inherited_citation_context or {}
        )
        if isinstance(inherited_appendix, str) and inherited_appendix.strip():
            prompt_override = (
                f"{prepared.effective_prompt}\n\n{inherited_appendix}"
                if prepared.effective_prompt.strip()
                else inherited_appendix
            )
    return prompt_override


async def preview_step_execution_context(
    *,
    step: RuntimeStep,
    state: RunExecutionState,
    prepared: PreparedStepExecution,
    deps: StepExecutionRuntimeDeps,
) -> int:
    """Count the exact base package without RAG or provider/tool side effects."""
    if any(
        diagnostic.code == RUNTIME_INPUT_SOURCE_EMPTY_TEXT_DIAGNOSTIC_CODE
        for diagnostic in prepared.diagnostics
    ):
        raise TypedIOValidationException(
            f"Step {step.step_order}: mapped input contains a source with no readable text.",
            code=FlowApiErrorCode.TYPED_IO_EMPTY_EXTRACTION.value,
        )
    mcp_servers = getattr(prepared.assistant, "mcp_servers", [])
    if mcp_servers:
        raise TypedIOValidationException(
            f"Step {step.step_order}: mapped preflight does not support mutable "
            "external MCP tools; remove them from the published Flow assistant.",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
        )
    citation_mode = citation_mode_for_step(step)
    inherited_citation_context = (
        collect_inherited_citation_context(step=step, state=state)
        if citation_mode == CITATION_MODE_INLINE_INREF_SIDECAR
        else None
    )
    prompt_override = _completion_prompt_override(
        prepared=prepared,
        citation_mode=citation_mode,
        inherited_citation_context=inherited_citation_context,
    )
    try:
        preview = await prepared.assistant.preview_response_context(
            question=prepared.step_input.text,
            completion_service=deps.completion_service,
            files=prepared.llm_files,
            prompt_override=prompt_override,
            version=2 if citation_mode == CITATION_MODE_INLINE_INREF_SIDECAR else 1,
        )
    except ContextWindowExceededError as exc:
        raise _typed_context_window_error(
            exc,
            step=step,
            prepared=prepared,
            deps=deps,
            effective_prompt=prompt_override,
        ) from exc
    return preview.token_count


async def complete_step_execution(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    prepared: PreparedStepExecution,
    deps: StepExecutionRuntimeDeps,
) -> StepExecutionOutput:
    diagnostics = list(prepared.diagnostics)
    citation_mode = citation_mode_for_step(step)
    inherited_citation_context = (
        collect_inherited_citation_context(step=step, state=state)
        if citation_mode == CITATION_MODE_INLINE_INREF_SIDECAR
        else None
    )

    rag_query_derivation = derive_rag_retrieval_query(
        step=step,
        input_text=prepared.step_input.text,
    )
    info_blob_chunks, rag_metadata, rag_diagnostics = await deps.retrieve_rag_chunks(
        assistant=prepared.assistant,
        question=rag_query_derivation.query,
        run_id=run.id,
        step_order=step.step_order,
    )
    diagnostics.extend(rag_diagnostics)
    if rag_metadata is not None:
        rag_metadata["query_derivation"] = rag_query_derivation.to_metadata()
        if step.retrieval_policy is not None:
            rag_metadata["retrieval_policy"] = step.retrieval_policy.model_dump(
                mode="json"
            )
    if (
        rag_query_derivation.input_truncated
        and isinstance(rag_metadata, dict)
        and rag_metadata.get("attempted") is True
    ):
        diagnostics.append(
            StepDiagnostic(
                code="rag_retrieval_query_truncated",
                message=(
                    f"Step {step.step_order}: knowledge retrieval query was truncated "
                    f"to {RAG_RETRIEVAL_QUERY_CHAR_LIMIT} characters."
                ),
                severity="warning",
            )
        )

    retrieval_status = (
        rag_metadata.get("status") if isinstance(rag_metadata, dict) else None
    )
    fail_closed_reason = (
        "query_truncated"
        if rag_query_derivation.input_truncated
        and isinstance(rag_metadata, dict)
        and rag_metadata.get("attempted") is True
        else retrieval_status
    )
    if (
        step.retrieval_policy is not None
        and step.retrieval_policy.mode == "fail_closed"
        and (
            fail_closed_reason == "query_truncated"
            or fail_closed_reason in RAG_RETRIEVAL_FAIL_CLOSED_STATUSES
        )
    ):
        diagnostics.append(
            StepDiagnostic(
                code="rag_retrieval_fail_closed",
                message=(
                    f"Step {step.step_order}: fail-closed knowledge retrieval policy "
                    f"stopped this completion call after '{fail_closed_reason}'; "
                    "provider I/O for this call was not started."
                ),
                severity="error",
            )
        )
        failed_input_payload = dict(prepared.input_payload_for_result)
        failed_input_payload["rag"] = rag_metadata
        failed_input_payload["diagnostics"] = [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "severity": diagnostic.severity,
            }
            for diagnostic in diagnostics
        ]
        raise attach_typed_failure_context(
            TypedIOValidationException(
                f"Step {step.step_order}: required knowledge retrieval ended with "
                f"'{fail_closed_reason}'; provider I/O for this completion call "
                "was not started.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
            ),
            input_payload_for_result=failed_input_payload,
            effective_prompt=prepared.effective_prompt,
        )

    model_kwargs = prepared.assistant.completion_model_kwargs
    original_kwargs = model_kwargs
    cache_key = json_mode_cache_key(prepared.assistant)
    response_format_plan = resolve_json_response_format_plan(
        step=step,
        assistant=prepared.assistant,
        state=state,
    )
    native_json_object_attempted = response_format_plan.native_json_object_attempted
    if native_json_object_attempted:
        try:
            model_kwargs = prepared.assistant.completion_model_kwargs.model_copy(
                update={"response_format": {"type": "json_object"}}
            )
        except Exception:
            logger.warning(
                "Failed to enable native JSON mode for flow step execution.",
                extra={
                    "run_id": str(run.id),
                    "step_order": step.step_order,
                    "cache_key": cache_key,
                },
                exc_info=True,
            )
            state.json_mode_supported[cache_key] = False
            # The plan keeps fallback available because the original kwargs may
            # still carry an authored response format.
            native_json_object_attempted = False
    elif response_format_plan.strip_stored_response_format:
        model_kwargs = prepared.assistant.completion_model_kwargs.model_copy(
            update={"response_format": None}
        )

    if deps.logger is not None:
        deps.logger.info(
            "flow_executor.llm_call run_id=%s step_order=%d timeout=%s "
            "native_json_object_attempted=%s",
            run.id,
            step.step_order,
            deps.llm_request_timeout_seconds,
            native_json_object_attempted,
        )
    prompt_override = _completion_prompt_override(
        prepared=prepared,
        citation_mode=citation_mode,
        inherited_citation_context=inherited_citation_context,
    )
    step_deadline_monotonic = (
        asyncio.get_event_loop().time() + deps.llm_request_timeout_seconds
    )
    try:
        response = await call_assistant_with_timeout(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
            model_kwargs=model_kwargs,
            info_blob_chunks=info_blob_chunks,
            prompt_override=prompt_override,
            version=2 if citation_mode == CITATION_MODE_INLINE_INREF_SIDECAR else 1,
            provider_call_reason="initial",
            step_deadline_monotonic=step_deadline_monotonic,
        )
    except ProviderCapabilityRejectedException as model_exc:
        if (
            response_format_plan.fallback_call_possible
            and model_exc.capability == "response_format"
            and model_exc.retry_without_capability_safe
        ):
            state.json_mode_supported[cache_key] = False
            fallback_kwargs = original_kwargs.model_copy(
                update={"response_format": None}
            )
            response = await call_assistant_with_timeout(
                step=step,
                run=run,
                state=state,
                prepared=prepared,
                deps=deps,
                model_kwargs=fallback_kwargs,
                info_blob_chunks=info_blob_chunks,
                prompt_override=prompt_override,
                version=2 if citation_mode == CITATION_MODE_INLINE_INREF_SIDECAR else 1,
                provider_call_reason="capability_fallback",
                step_deadline_monotonic=step_deadline_monotonic,
            )
        else:
            raise

    if deps.logger is not None:
        deps.logger.info(
            "flow_executor.llm_done run_id=%s step_order=%d tokens=%s",
            run.id,
            step.step_order,
            response.total_token_count,
        )

    completion = response.completion
    if isinstance(completion, str):
        raw_full_text = completion
        tool_calls = None
        reasoning_tokens = 0
    else:
        completion = (
            completion
            if isinstance(completion, Completion)
            else Completion(text=str(completion))
        )
        raw_full_text = completion.text or ""
        tool_calls = (
            [tc.__dict__ for tc in completion.tool_calls_metadata]
            if completion.tool_calls_metadata
            else None
        )
        reasoning_tokens = completion.reasoning_token_count or 0

    response_model_info = getattr(response, "model", None)
    response_usage = getattr(response, "usage", None)
    num_tokens_input = (
        response_usage.prompt_tokens
        if response_usage is not None and response_usage.prompt_tokens is not None
        else response.total_token_count
    )
    num_tokens_output = (
        response_usage.completion_tokens
        if response_usage is not None and response_usage.completion_tokens is not None
        else count_tokens(
            raw_full_text, _resolve_litellm_model_name(prepared.assistant) or ""
        )
        + reasoning_tokens
    )
    rag_metadata = apply_prompt_context_trace(
        rag_metadata,
        knowledge_trace=getattr(response, "knowledge_trace", None),
    )
    rag_metadata = apply_citation_tracking(rag_metadata, citation_mode=citation_mode)
    citation_sidecar = build_runtime_citation_sidecar(
        raw_completion_text=raw_full_text,
        rag_metadata=rag_metadata,
        citation_mode=citation_mode,
        inherited_context=inherited_citation_context,
    )
    full_text = (
        strip_inline_reference_tags(raw_full_text)
        if citation_mode == CITATION_MODE_INLINE_INREF_SIDECAR
        else raw_full_text
    )

    if deps.logger is not None:
        deps.logger.info(
            "flow_executor.typed_output_processing run_id=%s step_order=%d output_type=%s",
            run.id,
            step.step_order,
            step.output_type,
        )
    try:
        typed_output = await deps.process_typed_output(
            full_text=full_text,
            step=step,
            run=run,
        )
    except TypedIOValidationException as exc:
        raise attach_typed_failure_context(
            exc,
            input_payload_for_result=prepared.input_payload_for_result,
            effective_prompt=prompt_override,
        ) from exc

    diagnostics.extend(typed_output.diagnostics)
    structured_output = typed_output.structured_output
    artifacts = typed_output.artifacts

    if deps.logger is not None:
        deps.logger.info(
            "flow_executor.typed_output_done run_id=%s step_order=%d output_type=%s "
            "full_text_len=%d has_structured=%s has_artifacts=%s",
            run.id,
            step.step_order,
            step.output_type,
            len(full_text),
            structured_output is not None,
            artifacts is not None and len(artifacts) > 0,
        )

    persisted_text, generated_file_ids = await deps.apply_output_cap(
        text=full_text,
        run=run,
        step=step,
    )
    return StepExecutionOutput(
        input_text=prepared.step_input.text,
        source_text=prepared.step_input.source_text,
        input_source=prepared.step_input.input_source,
        used_question_binding=prepared.step_input.used_question_binding,
        full_text=full_text,
        persisted_text=persisted_text,
        generated_file_ids=generated_file_ids,
        tool_calls_metadata=tool_calls,
        num_tokens_input=num_tokens_input,
        num_tokens_output=num_tokens_output,
        effective_prompt=prompt_override,
        model_parameters_json=effective_model_parameters(prepared.assistant),
        requested_model=requested_model_name(prepared.assistant),
        response_model=getattr(response_model_info, "name", None),
        provider=getattr(response_model_info, "provider_type", None),
        finish_reason=infer_finish_reason(completion=completion, tool_calls=tool_calls),
        provider_response_id=getattr(completion, "provider_response_id", None),
        contract_validation=prepared.contract_validation,
        structured_output=structured_output,
        artifacts=artifacts,
        diagnostics=diagnostics,
        rag_metadata=rag_metadata,
        transcription_metadata=prepared.step_input.transcription_metadata,
        runtime_input_metadata=prepared.step_input.runtime_input_metadata,
        citation_sidecar=citation_sidecar,
        raw_completion_text=(
            raw_full_text
            if citation_sidecar is not None
            and bool(citation_sidecar.get("citation_observed"))
            else None
        ),
    )
