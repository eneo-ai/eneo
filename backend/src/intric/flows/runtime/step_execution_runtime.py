from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from intric.ai_models.completion_models.completion_model import Completion
from intric.flows.flow import FlowRun, FlowStepResultStatus
from intric.flows.output_modes import transcribe_only_violation
from intric.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
)
from intric.flows.runtime.step_input_validation import (
    validate_input_contract,
    validate_runtime_input_policy,
)
from intric.flows.runtime.step_result_builder import build_transcribe_only_rag_metadata
from intric.main.exceptions import TypedIOValidationException

try:
    from litellm import get_supported_openai_params as _litellm_get_supported_openai_params
except Exception:  # pragma: no cover - defensive import guard
    _litellm_get_supported_openai_params = None


@dataclass
class PreparedStepExecution:
    assistant: Any
    step_input: StepInputValue
    effective_prompt: str
    input_payload_for_result: dict[str, Any]
    contract_validation: dict[str, Any] | None
    diagnostics: list[StepDiagnostic]
    llm_files: list[Any]


@dataclass(frozen=True)
class StepExecutionRuntimeDeps:
    variable_resolver: Any
    completion_service: Any
    load_assistant: Any
    resolve_step_input: Any
    retrieve_rag_chunks: Any
    process_typed_output: Any
    apply_output_cap: Any
    attach_typed_failure_context: Any
    effective_model_parameters: Any
    json_mode_cache_key: Any
    is_json_mode_rejection: Any
    count_tokens: Any
    logger: Any | None = None
    rag_retrieval_timeout_seconds: float = 30


def _resolve_litellm_model_name(assistant: Any) -> str | None:
    completion_model = getattr(assistant, "completion_model", None)
    if completion_model is None:
        return None

    explicit_name = getattr(completion_model, "litellm_model_name", None)
    if isinstance(explicit_name, str) and explicit_name.strip():
        return explicit_name.strip()

    provider = getattr(completion_model, "provider_type", None)
    name = getattr(completion_model, "name", None)
    if isinstance(provider, str) and provider.strip() and isinstance(name, str) and name.strip():
        return f"{provider.strip()}/{name.strip()}"
    return None


def detect_native_json_output_support(assistant: Any) -> bool | None:
    """
    Return whether LiteLLM reports native response_format support for this model.

    None means capability could not be determined, so callers should preserve the
    previous optimistic behavior instead of tightening compatibility.
    """
    if _litellm_get_supported_openai_params is None:
        return None

    litellm_model_name = _resolve_litellm_model_name(assistant)
    if not litellm_model_name:
        return None

    try:
        supported = _litellm_get_supported_openai_params(model=litellm_model_name)
    except Exception:
        return None

    if not supported:
        return None

    return "response_format" in {str(item) for item in supported}


def json_mode_cache_key(assistant: Any) -> str:
    cm = assistant.completion_model
    provider = getattr(cm, "provider_type", "unknown") or "unknown"
    name = cm.name if cm else "unknown"
    mid = str(cm.id) if cm and cm.id else "none"
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


def build_output_payload(output: StepExecutionOutput) -> dict[str, Any]:
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


def effective_model_parameters(assistant: Any) -> dict[str, Any]:
    kwargs = assistant.completion_model_kwargs.model_dump(exclude_none=True)  # type: ignore[attr-defined]
    completion_model = assistant.completion_model  # type: ignore[attr-defined]
    return {
        "model_id": str(completion_model.id) if completion_model and completion_model.id else None,
        "model_name": completion_model.name if completion_model else None,
        "provider": getattr(completion_model, "provider_type", None),
        **kwargs,
    }


def augment_prompt_for_json_output(
    *,
    output_type: str,
    output_contract: dict[str, Any] | None,
    prompt: str,
) -> str:
    if output_type != "json":
        return prompt

    instructions = [
        "Return ONLY valid JSON.",
        "Do not include markdown code fences, commentary, or any surrounding text.",
        "The top-level JSON value must be an object or array.",
    ]
    if output_contract:
        schema_json = json.dumps(output_contract, ensure_ascii=False, sort_keys=True)
        instructions.extend(
            [
                "Follow this JSON Schema exactly:",
                schema_json,
            ]
        )

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
    context_results = [item for item in state.prior_results if item.status == FlowStepResultStatus.COMPLETED]
    context = deps.variable_resolver.build_context(
        run.input_payload_json,
        context_results,
        current_step_order=step.step_order,
        step_names_by_order=state.step_names_by_order,
    )
    assistant = await deps.load_assistant(step.assistant_id, state)
    prompt_text = assistant.get_prompt_text()
    effective_prompt = ""
    input_payload_for_result = {
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

    effective_prompt = deps.variable_resolver.interpolate(prompt_text, context) if prompt_text else ""
    effective_prompt = augment_prompt_for_json_output(
        output_type=step.output_type,
        output_contract=step.output_contract,
        prompt=effective_prompt,
    )

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
            input_payload_for_result["contract_validation"] = contract_validation_payload
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

    llm_files: list[Any] = []
    if policy is not None and policy.channel == "files_only":
        llm_files = step_input.files or []

    return PreparedStepExecution(
        assistant=assistant,
        step_input=step_input,
        effective_prompt=effective_prompt,
        input_payload_for_result=input_payload_for_result,
        contract_validation=contract_validation,
        diagnostics=list(step_input.diagnostics),
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
    if step.output_type == "json":
        cached_json_mode_support = state.json_mode_supported.get(cache_key)
        if cached_json_mode_support is None:
            detected_json_mode_support = detect_native_json_output_support(prepared.assistant)
            if detected_json_mode_support is not None:
                state.json_mode_supported[cache_key] = detected_json_mode_support
                cached_json_mode_support = detected_json_mode_support
        if cached_json_mode_support is not False:
            try:
                model_kwargs = prepared.assistant.completion_model_kwargs.model_copy(
                    update={"response_format": {"type": "json_object"}}
                )
            except Exception:
                state.json_mode_supported[cache_key] = False

    if deps.logger is not None:
        deps.logger.info("flow_executor.llm_call run_id=%s step_order=%d", run.id, step.step_order)
    try:
        response = await prepared.assistant.get_response(
            question=prepared.step_input.text,
            completion_service=deps.completion_service,
            model_kwargs=model_kwargs,
            files=prepared.llm_files,
            info_blob_chunks=info_blob_chunks,
            stream=False,
            prompt_override=prepared.effective_prompt,
        )
    except Exception as model_exc:
        if step.output_type == "json" and deps.is_json_mode_rejection(model_exc):
            state.json_mode_supported[cache_key] = False
            response = await prepared.assistant.get_response(
                question=prepared.step_input.text,
                completion_service=deps.completion_service,
                model_kwargs=original_kwargs,
                files=prepared.llm_files,
                info_blob_chunks=info_blob_chunks,
                stream=False,
                prompt_override=prepared.effective_prompt,
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
            effective_prompt=prepared.effective_prompt,
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
        num_tokens_input=response.total_token_count,
        num_tokens_output=deps.count_tokens(full_text) + reasoning_tokens,
        effective_prompt=prepared.effective_prompt,
        model_parameters_json=deps.effective_model_parameters(prepared.assistant),
        contract_validation=prepared.contract_validation,
        structured_output=structured_output,
        artifacts=artifacts,
        diagnostics=diagnostics,
        rag_metadata=rag_metadata,
        transcription_metadata=prepared.step_input.transcription_metadata,
    )
