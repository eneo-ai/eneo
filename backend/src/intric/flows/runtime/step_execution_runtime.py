from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Protocol, cast
from uuid import UUID

from intric.ai_models.completion_models.completion_model import Completion
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.completion_models.infrastructure.tenant_model_capabilities import (
    get_supported_openai_params,
)
from intric.files.file_models import File
from intric.flows.citation_sidecar import (
    CITATION_MODE_INLINE_INREF_SIDECAR,
    build_citation_sidecar,
    resolve_citation_mode,
    strip_inline_reference_tags,
)
from intric.flows.domain.flow import FlowRun, FlowStepResult, FlowStepResultStatus
from intric.flows.output_modes import transcribe_only_violation
from intric.flows.runtime.inherited_citations import (
    build_inherited_citation_prompt_appendix,
    collect_inherited_citation_context,
)
from intric.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
)
from intric.flows.runtime.protocols import RuntimeAssistantProtocol
from intric.flows.runtime.step_input_validation import (
    validate_input_contract,
    validate_runtime_input_policy,
)
from intric.flows.runtime.step_result_builder import build_transcribe_only_rag_metadata
from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from intric.main.exceptions import TypedIOValidationException


def _string_key_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    raw_dict = cast(dict[object, Any], value)
    return {str(key): item for key, item in raw_dict.items()}


logger = logging.getLogger(__name__)


class VariableResolverProtocol(Protocol):
    def build_context(
        self,
        flow_input: dict[str, Any] | None,
        prior_results: list[FlowStepResult],
        *,
        current_step_order: int | None = None,
        step_names_by_order: dict[int, str] | None = None,
        current_step_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def interpolate(self, template: str, context: dict[str, Any]) -> str: ...


class CountTokensFn(Protocol):
    def __call__(self, text: str) -> int: ...


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
        assistant_prompt_text: str | None,
        state: RunExecutionState,
        version_metadata: dict[str, Any] | None,
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
    ) -> Awaitable[
        tuple[dict[str, Any] | list[Any] | None, list[dict[str, Any]] | None]
    ]: ...


class ApplyOutputCapFn(Protocol):
    def __call__(
        self,
        *,
        text: str,
        run: FlowRun,
        step: RuntimeStep,
    ) -> Awaitable[tuple[str, list[UUID]]]: ...


class AttachTypedFailureContextFn(Protocol):
    def __call__(
        self,
        exc: TypedIOValidationException,
        *,
        input_payload_for_result: dict[str, Any],
        effective_prompt: str,
    ) -> TypedIOValidationException: ...


class EffectiveModelParametersFn(Protocol):
    def __call__(self, assistant: RuntimeAssistantProtocol) -> dict[str, Any]: ...


class JsonModeCacheKeyFn(Protocol):
    def __call__(self, assistant: RuntimeAssistantProtocol) -> str: ...


class JsonModeRejectionFn(Protocol):
    def __call__(self, exc: Exception) -> bool: ...


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
    attach_typed_failure_context: AttachTypedFailureContextFn
    effective_model_parameters: EffectiveModelParametersFn
    json_mode_cache_key: JsonModeCacheKeyFn
    is_json_mode_rejection: JsonModeRejectionFn
    count_tokens: CountTokensFn
    logger: logging.Logger | None = None
    llm_request_timeout_seconds: float = 600
    rag_retrieval_timeout_seconds: float = 30


def _resolve_litellm_model_name(assistant: RuntimeAssistantProtocol) -> str | None:
    completion_model = assistant.completion_model
    if completion_model is None:
        return None

    explicit_name = completion_model.litellm_model_name
    if explicit_name and explicit_name.strip():
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
        payload.setdefault("legacy_prompt_binding_used", False)
        setattr(exc, "input_payload_json", payload)
    existing_prompt = getattr(exc, "effective_prompt", None)
    if not isinstance(existing_prompt, str):
        setattr(exc, "effective_prompt", effective_prompt)
    return exc


def is_json_mode_rejection(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(term in msg for term in ("response_format", "json_object", "json mode"))


async def call_assistant_with_timeout(
    *,
    step: RuntimeStep,
    run: FlowRun,
    prepared: PreparedStepExecution,
    deps: StepExecutionRuntimeDeps,
    model_kwargs: Any,
    info_blob_chunks: list[InfoBlobChunkInDBWithScore],
    prompt_override: str,
    version: int,
    step_deadline_monotonic: float | None = None,
) -> Any:
    # When a step deadline is supplied, the json-mode rejection retry shares
    # the same wall-clock budget as the initial call. Without this, a step
    # that consumes most of its timeout on the first attempt is granted a
    # fresh per-call budget for the fallback retry — silently doubling the
    # bound the executor's outer asyncio.wait_for is supposed to enforce.
    if step_deadline_monotonic is None:
        timeout = deps.llm_request_timeout_seconds
    else:
        loop = asyncio.get_event_loop()
        timeout = max(0.0, step_deadline_monotonic - loop.time())

    if timeout <= 0:
        if deps.logger is not None:
            deps.logger.warning(
                "flow_executor.llm_timeout run_id=%s step_order=%d timeout=%s",
                run.id,
                step.step_order,
                deps.llm_request_timeout_seconds,
            )
        raise deps.attach_typed_failure_context(
            TypedIOValidationException(
                f"Step {step.step_order}: LLM request exceeded "
                f"{deps.llm_request_timeout_seconds:g}s timeout.",
                code="flow_llm_request_timeout",
            ),
            input_payload_for_result=prepared.input_payload_for_result,
            effective_prompt=prepared.effective_prompt,
        )

    try:
        return await asyncio.wait_for(
            prepared.assistant.get_response(
                question=prepared.step_input.text,
                completion_service=deps.completion_service,
                model_kwargs=model_kwargs,
                files=prepared.llm_files,
                info_blob_chunks=info_blob_chunks,
                stream=False,
                prompt_override=prompt_override,
                version=version,
            ),
            timeout=timeout,
        )
    except TimeoutError as exc:
        if deps.logger is not None:
            deps.logger.warning(
                "flow_executor.llm_timeout run_id=%s step_order=%d timeout=%s",
                run.id,
                step.step_order,
                deps.llm_request_timeout_seconds,
            )
        raise deps.attach_typed_failure_context(
            TypedIOValidationException(
                f"Step {step.step_order}: LLM request exceeded "
                f"{deps.llm_request_timeout_seconds:g}s timeout.",
                code="flow_llm_request_timeout",
            ),
            input_payload_for_result=prepared.input_payload_for_result,
            effective_prompt=prepared.effective_prompt,
        ) from exc


def build_output_payload(output: StepExecutionOutput) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": output.persisted_text,
        "webhook_delivered": False,
    }
    if output.structured_output is not None:
        payload["structured"] = output.structured_output
    if output.output_payload_extensions:
        payload.update(output.output_payload_extensions)
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
    if step.output_type != "text":
        return "off"
    if step.output_mode in {"template_fill", "transcribe_only"}:
        return "off"
    return citation_mode


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


def augment_prompt_for_typed_output(
    *,
    output_type: str,
    output_contract: dict[str, Any] | None,
    prompt: str,
) -> str:
    if output_type == "json":
        instructions = [
            "Return ONLY valid JSON.",
            "Do not include markdown code fences, commentary, or any surrounding text.",
            "The top-level JSON value must be an object or array.",
        ]
        if output_contract is not None:
            schema_json = json.dumps(
                output_contract, ensure_ascii=False, sort_keys=True
            )
            instructions.extend(
                [
                    "Follow this JSON Schema exactly:",
                    schema_json,
                ]
            )
    elif output_type in {"pdf", "docx"}:
        if output_contract is not None:
            artifact_name = "PDF" if output_type == "pdf" else "DOCX"
            schema_json = json.dumps(
                output_contract, ensure_ascii=False, sort_keys=True
            )
            instructions = [
                f"The system will validate your JSON and render it into a {artifact_name} file after you respond.",
                "Return ONLY valid JSON.",
                "Do not include markdown code fences, commentary, or any surrounding text.",
                "The top-level JSON value must be an object or array.",
                "Use plain text for JSON string values; do not include Markdown formatting markers inside strings.",
                "Follow this JSON Schema exactly:",
                schema_json,
            ]
        else:
            artifact_name = "PDF" if output_type == "pdf" else "DOCX"
            instructions = [
                f"The system will render your answer into a {artifact_name} file after you respond.",
                "Return only the document body as Markdown/plain text content.",
                "Do not output binary file contents, base64, XML/ZIP internals, or PDF object syntax.",
                "For PDF output specifically, do not start the response with %PDF-.",
            ]
    else:
        return prompt

    suffix = "\n".join(instructions)
    return f"{prompt}\n\n{suffix}" if prompt.strip() else suffix


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
    deps: StepExecutionRuntimeDeps,
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
    )
    assistant = await deps.load_assistant(step.assistant_id, state)
    prompt_text = assistant.get_prompt_text()
    effective_prompt = ""
    input_payload_for_result: dict[str, Any] = {
        "text": "",
        "source_text": "",
        "input_source": step.input_source,
        "used_question_binding": False,
        "legacy_prompt_binding_used": False,
    }
    try:
        step_input = await deps.resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=state.prior_results,
            assistant_prompt_text=prompt_text,
            state=state,
            version_metadata=version_metadata,
        )
    except TypedIOValidationException as exc:
        raise deps.attach_typed_failure_context(
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
        raise deps.attach_typed_failure_context(
            exc,
            input_payload_for_result=input_payload_for_result,
            effective_prompt=effective_prompt,
        ) from exc

    prompt_context = deps.variable_resolver.build_context(
        run.input_payload_json,
        context_results,
        current_step_order=step.step_order,
        step_names_by_order=state.step_names_by_order,
        current_step_input=step_input.runtime_input_metadata,
    )
    effective_prompt = (
        deps.variable_resolver.interpolate(prompt_text, prompt_context)
        if prompt_text
        else ""
    )
    effective_prompt = augment_prompt_for_typed_output(
        output_type=step.output_type,
        output_contract=step.output_contract,
        prompt=effective_prompt,
    )
    diagnostics = list(step_input.diagnostics)

    if (
        step.input_type == "json"
        and step_input.used_question_binding
        and step_input.structured is None
    ):
        contract_validation = None
        diagnostics.append(
            StepDiagnostic(
                code="flow_input_contract_skipped_for_binding",
                message=(
                    f"Step {step.step_order}: skipped JSON input contract validation "
                    "because explicit underlag replaced the previous structured input."
                ),
                severity="info",
            )
        )
    else:
        try:
            contract_validation = validate_input_contract(
                step_order=step.step_order,
                input_type=step.input_type,
                input_contract=step.input_contract,
                text=step_input.text,
                structured=step_input.structured,
            )
        except TypedIOValidationException as exc:
            contract_validation_payload = getattr(exc, "contract_validation", None)
            if isinstance(contract_validation_payload, dict):
                input_payload_for_result["contract_validation"] = (
                    contract_validation_payload
                )
            raise deps.attach_typed_failure_context(
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
    if step.output_mode == "transcribe_only":
        mode_error = transcribe_only_violation(
            step_order=step.step_order,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if mode_error is not None:
            raise deps.attach_typed_failure_context(
                TypedIOValidationException(
                    mode_error,
                    code="typed_io_invalid_output_mode_combination",
                ),
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt=prepared.effective_prompt,
            )
        diagnostics.append(
            StepDiagnostic(
                code="audio_transcribe_only_used",
                message=(
                    f"Step {step.step_order}: transcribe_only mode used; "
                    "completion LLM and RAG were skipped."
                ),
                severity="info",
            )
        )
        rag_metadata = build_transcribe_only_rag_metadata(
            timeout_seconds=deps.rag_retrieval_timeout_seconds
        )
        persisted_text, generated_file_ids = await deps.apply_output_cap(
            text=prepared.step_input.text,
            run=run,
            step=step,
        )
        return StepExecutionOutput(
            input_text=prepared.step_input.text,
            source_text=prepared.step_input.source_text,
            input_source=prepared.step_input.input_source,
            used_question_binding=prepared.step_input.used_question_binding,
            legacy_prompt_binding_used=prepared.step_input.legacy_prompt_binding_used,
            full_text=prepared.step_input.text,
            persisted_text=persisted_text,
            generated_file_ids=generated_file_ids,
            tool_calls_metadata=None,
            num_tokens_input=0,
            num_tokens_output=0,
            effective_prompt="",
            model_parameters_json={"mode": "transcribe_only"},
            contract_validation=prepared.contract_validation,
            structured_output=None,
            artifacts=None,
            diagnostics=diagnostics,
            rag_metadata=rag_metadata,
            transcription_metadata=prepared.step_input.transcription_metadata,
            runtime_input_metadata=prepared.step_input.runtime_input_metadata,
        )

    info_blob_chunks, rag_metadata, rag_diagnostics = await deps.retrieve_rag_chunks(
        assistant=prepared.assistant,
        question=prepared.step_input.text,
        run_id=run.id,
        step_order=step.step_order,
    )
    diagnostics.extend(rag_diagnostics)

    model_kwargs = prepared.assistant.completion_model_kwargs
    original_kwargs = model_kwargs
    cache_key = deps.json_mode_cache_key(prepared.assistant)
    native_json_object_requested = _should_request_native_json_object_mode(step)
    if native_json_object_requested:
        cached_json_mode_support = state.json_mode_supported.get(cache_key)
        if cached_json_mode_support is None:
            detected_json_mode_support = detect_native_json_output_support(
                prepared.assistant
            )
            if detected_json_mode_support is not None:
                state.json_mode_supported[cache_key] = detected_json_mode_support
                cached_json_mode_support = detected_json_mode_support
        if cached_json_mode_support is not False:
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

    if deps.logger is not None:
        deps.logger.info(
            "flow_executor.llm_call run_id=%s step_order=%d", run.id, step.step_order
        )
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
    step_deadline_monotonic = (
        asyncio.get_event_loop().time() + deps.llm_request_timeout_seconds
    )
    try:
        response = await call_assistant_with_timeout(
            step=step,
            run=run,
            prepared=prepared,
            deps=deps,
            model_kwargs=model_kwargs,
            info_blob_chunks=info_blob_chunks,
            prompt_override=prompt_override,
            version=2 if citation_mode == CITATION_MODE_INLINE_INREF_SIDECAR else 1,
            step_deadline_monotonic=step_deadline_monotonic,
        )
    except Exception as model_exc:
        if native_json_object_requested and deps.is_json_mode_rejection(model_exc):
            state.json_mode_supported[cache_key] = False
            response = await call_assistant_with_timeout(
                step=step,
                run=run,
                prepared=prepared,
                deps=deps,
                model_kwargs=original_kwargs,
                info_blob_chunks=info_blob_chunks,
                prompt_override=prompt_override,
                version=2 if citation_mode == CITATION_MODE_INLINE_INREF_SIDECAR else 1,
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
        structured_output, artifacts = await deps.process_typed_output(
            full_text=full_text,
            step=step,
            run=run,
        )
    except TypedIOValidationException as exc:
        raise deps.attach_typed_failure_context(
            exc,
            input_payload_for_result=prepared.input_payload_for_result,
            effective_prompt=prompt_override,
        ) from exc

    if deps.logger is not None:
        deps.logger.info(
            "flow_executor.typed_output_done run_id=%s step_order=%d has_structured=%s has_artifacts=%s",
            run.id,
            step.step_order,
            structured_output is not None,
            artifacts is not None and len(artifacts) > 0,
        )

    persisted_text, generated_file_ids = await deps.apply_output_cap(
        text=full_text,
        run=run,
        step=step,
    )
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
        else deps.count_tokens(raw_full_text) + reasoning_tokens
    )
    return StepExecutionOutput(
        input_text=prepared.step_input.text,
        source_text=prepared.step_input.source_text,
        input_source=prepared.step_input.input_source,
        used_question_binding=prepared.step_input.used_question_binding,
        legacy_prompt_binding_used=prepared.step_input.legacy_prompt_binding_used,
        full_text=full_text,
        persisted_text=persisted_text,
        generated_file_ids=generated_file_ids,
        tool_calls_metadata=tool_calls,
        num_tokens_input=num_tokens_input,
        num_tokens_output=num_tokens_output,
        effective_prompt=prompt_override,
        model_parameters_json=deps.effective_model_parameters(prepared.assistant),
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


def _should_request_native_json_object_mode(step: RuntimeStep) -> bool:
    if step.output_type == "json":
        if step.output_contract is None:
            return True
        return _schema_prefers_object_value(step.output_contract)
    if step.output_type in {"pdf", "docx"} and step.output_contract is not None:
        return _schema_prefers_object_value(step.output_contract)
    return False


def _schema_prefers_object_value(schema: dict[str, Any]) -> bool:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type == "object"
    if isinstance(raw_type, list):
        declared = {
            item for item in cast(list[object], raw_type) if isinstance(item, str)
        }
        return "object" in declared and "array" not in declared
    if isinstance(schema.get("properties"), dict):
        return True
    if "items" in schema:
        return False
    return False
