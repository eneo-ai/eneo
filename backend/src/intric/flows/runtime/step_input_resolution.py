from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from intric.flows.flow import FlowRun, FlowStepResult
from intric.flows.runtime_input import build_runtime_input_config
from intric.flows.runtime.input_files import (
    load_files_by_requested_ids,
    parse_requested_file_ids,
)
from intric.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepInputValue,
)
from intric.flows.runtime.transcription_runtime import (
    AudioRuntimeDeps,
    AudioRuntimeRequest,
    resolve_transcribe_and_attach_audio_input,
)
from intric.main.exceptions import BadRequestException, TypedIOValidationException


@dataclass(frozen=True)
class StepInputResolutionDeps:
    variable_resolver: Any
    resolve_http_input_source_text: Callable[..., Awaitable[tuple[str, dict[str, Any] | list[Any] | None]]]
    file_repo: Any
    user_id: Any
    transcriber: Any | None
    space_repo: Any
    flow_run_repo: Any
    audit_service: Any | None
    actor: Any
    max_generic_files: int | None
    max_audio_files: int | None
    max_inline_text_bytes: int
    logger: Any


async def resolve_step_input(
    *,
    step: RuntimeStep,
    context: dict[str, Any],
    run: FlowRun,
    prior_results: list[FlowStepResult],
    assistant_prompt_text: str | None = None,
    state: RunExecutionState | None = None,
    version_metadata: dict[str, Any] | None = None,
    deps: StepInputResolutionDeps,
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
    if step.input_type == "audio" and step.input_source != "flow_input":
        raise TypedIOValidationException(
            f"Step {step.step_order}: input_type 'audio' is only supported with input_source 'flow_input'.",
            code="typed_io_audio_source_unsupported",
        )
    structured: dict[str, Any] | list[Any] | None = None
    if step.input_source in ("http_get", "http_post"):
        source_text, structured = await deps.resolve_http_input_source_text(
            step=step,
            run=run,
            context=context,
        )
    else:
        source_text = resolve_input_source_text(
            input_source=step.input_source,
            run=run,
            step_order=step.step_order,
            prior_results=prior_results,
            state=state,
            logger=deps.logger,
        )
    input_text = source_text
    raw_extracted_text = ""
    used_question_binding = False
    legacy_prompt_binding_used = False
    diagnostics: list[StepDiagnostic] = []
    transcription_metadata: dict[str, Any] | None = None
    runtime_input_metadata: dict[str, Any] | None = None
    files = None
    runtime_input_config = build_runtime_input_config(step.input_config)
    runtime_input_text = ""
    requested_ids = _resolve_runtime_requested_ids(run=run, step=step)

    if requested_ids and runtime_input_config.enabled:
        file_cache = state.file_cache if state else None
        files = await load_files_by_requested_ids(
            file_repo=deps.file_repo,
            requested_ids=requested_ids,
            user_id=deps.user_id,
            file_cache=file_cache,
        )
        returned_ids = {f.id for f in files}
        missing = [fid for fid in requested_ids if fid not in returned_ids]
        if missing:
            raise TypedIOValidationException(
                f"File(s) not found or not accessible: {missing}",
                code="typed_io_file_not_found",
            )

        if runtime_input_config.input_format == "audio":
            if deps.transcriber is None:
                raise TypedIOValidationException(
                    "Transcriber service is not available for audio input execution.",
                    code="typed_io_transcription_failed",
                )
            audio_request = AudioRuntimeRequest(
                run=run,
                step=step,
                context=context,
                version_metadata=version_metadata,
                files=files,
                requested_ids=requested_ids,
                max_audio_files=deps.max_audio_files,
                max_inline_text_bytes=deps.max_inline_text_bytes,
            )
            audio_deps = AudioRuntimeDeps(
                transcriber=deps.transcriber,
                space_repo=deps.space_repo,
                flow_run_repo=deps.flow_run_repo,
                audit_service=deps.audit_service,
                actor=deps.actor,
            )
            audio_resolution = await resolve_transcribe_and_attach_audio_input(
                request=audio_request,
                deps=audio_deps,
            )
            runtime_input_text = audio_resolution.text
            transcription_metadata = audio_resolution.transcription_metadata
        else:
            extracted = [
                str(f.text).strip()
                for f in files
                if isinstance(getattr(f, "text", None), str) and str(f.text).strip()
            ]
            if extracted:
                runtime_input_text = "\n\n".join(extracted)
                raw_extracted_text = runtime_input_text

        runtime_input_metadata = {
            "text": runtime_input_text,
            "file_ids": [str(file_id) for file_id in requested_ids],
            "extracted_text_length": len(runtime_input_text),
            "input_format": runtime_input_config.input_format,
        }

    bindings = step.input_bindings if isinstance(step.input_bindings, dict) else None
    if bindings is not None:
        question_template = bindings.get("question")
        if isinstance(question_template, str):
            interpolation_context = deps.variable_resolver.build_context(
                run.input_payload_json,
                prior_results,
                current_step_order=step.step_order,
                step_names_by_order=state.step_names_by_order if state else None,
                current_step_input=runtime_input_metadata,
            )
            interpolated_question = deps.variable_resolver.interpolate(
                question_template,
                interpolation_context,
            )
            if is_legacy_mirrored_question_binding(
                question_template=question_template,
                interpolated_question=interpolated_question,
                assistant_prompt_text=assistant_prompt_text,
            ):
                legacy_prompt_binding_used = True
            else:
                input_text = interpolated_question
                used_question_binding = True
                if runtime_input_metadata is not None and "step_input." not in question_template:
                    raise TypedIOValidationException(
                        f"Step {step.step_order}: explicit runtime-input bindings must reference step_input.*",
                        code="flow_runtime_input_not_consumed",
                    )

        legacy_text_template = bindings.get("text")
        if isinstance(legacy_text_template, str):
            legacy_prompt_binding_used = True

    if (
        files is None
        and step.input_source == "flow_input"
        and step.input_type in ("document", "image", "file", "audio")
    ):
        raw_file_ids = (run.input_payload_json or {}).get("file_ids", [])
        deps.logger.info(
            "flow_executor.file_resolve run_id=%s step_order=%d input_type=%s file_ids=%s",
            run.id, step.step_order, step.input_type, raw_file_ids,
        )
        requested_ids = parse_requested_file_ids(raw_file_ids=raw_file_ids)
        if requested_ids and step.input_type != "audio" and deps.max_generic_files is not None:
            if len(requested_ids) > deps.max_generic_files:
                raise TypedIOValidationException(
                    f"Step {step.step_order}: too many files "
                    f"({len(requested_ids)}, max {deps.max_generic_files}).",
                    code="typed_io_too_many_files",
                )
        if requested_ids:
            file_cache = state.file_cache if state else None
            files = await load_files_by_requested_ids(
                file_repo=deps.file_repo,
                requested_ids=requested_ids,
                user_id=deps.user_id,
                file_cache=file_cache,
            )
            returned_ids = {f.id for f in files}
            missing = [fid for fid in requested_ids if fid not in returned_ids]
            deps.logger.info(
                "flow_executor.file_resolve_result run_id=%s step_order=%d requested=%d returned=%d missing=%s",
                run.id, step.step_order, len(requested_ids), len(files), missing,
            )
            if missing:
                raise TypedIOValidationException(
                    f"File(s) not found or not accessible: {missing}",
                    code="typed_io_file_not_found",
                )
        if step.input_type == "audio":
            if deps.transcriber is None:
                raise TypedIOValidationException(
                    "Transcriber service is not available for audio input execution.",
                    code="typed_io_transcription_failed",
                )
            audio_request = AudioRuntimeRequest(
                run=run,
                step=step,
                context=context,
                version_metadata=version_metadata,
                files=files or [],
                requested_ids=requested_ids,
                max_audio_files=deps.max_audio_files,
                max_inline_text_bytes=deps.max_inline_text_bytes,
            )
            audio_deps = AudioRuntimeDeps(
                transcriber=deps.transcriber,
                space_repo=deps.space_repo,
                flow_run_repo=deps.flow_run_repo,
                audit_service=deps.audit_service,
                actor=deps.actor,
            )
            audio_resolution = await resolve_transcribe_and_attach_audio_input(
                request=audio_request,
                deps=audio_deps,
            )
            input_text = audio_resolution.text
            transcription_metadata = audio_resolution.transcription_metadata
            if audio_resolution.near_inline_limit_message is not None:
                diagnostics.append(
                    StepDiagnostic(
                        code="typed_io_transcript_near_limit",
                        message=audio_resolution.near_inline_limit_message,
                        severity="info",
                    )
                )
        elif step.input_type in ("document", "file") and files:
            extracted = [
                str(f.text).strip()
                for f in files
                if isinstance(getattr(f, "text", None), str) and str(f.text).strip()
            ]
            deps.logger.info(
                "flow_executor.document_text_extracted run_id=%s step_order=%d file_count=%d extracted_count=%d",
                run.id, step.step_order, len(files), len(extracted),
            )
            if extracted:
                input_text = "\n\n".join(extracted)
                raw_extracted_text = input_text

    if runtime_input_metadata is not None and not used_question_binding:
        input_text = _compose_runtime_and_chained_input(
            runtime_text=runtime_input_text,
            chained_text=source_text,
            replace_chain=(
                runtime_input_config.input_format == "audio"
                and step.output_mode == "transcribe_only"
            ),
        )
        if runtime_input_text:
            raw_extracted_text = runtime_input_text or raw_extracted_text

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

    enforce_inline_input_cap(
        text=input_text,
        step_order=step.step_order,
        input_source=step.input_source,
        max_inline_text_bytes=deps.max_inline_text_bytes,
    )

    if step.input_source in ("previous_step", "all_previous_steps"):
        has_substantive_input = False
        if step.input_source == "previous_step":
            has_substantive_input = bool(source_text.strip())
        else:
            for pr in prior_results:
                if pr.step_order < step.step_order and isinstance(pr.output_payload_json, dict):
                    if str(pr.output_payload_json.get("text", "")).strip():
                        has_substantive_input = True
                        break
        if not has_substantive_input:
            diagnostics.append(
                StepDiagnostic(
                    code="empty_prior_step_input",
                    message=(
                        f"Step {step.step_order}: input_source '{step.input_source}' resolved to "
                        f"empty text. The LLM received no substantive input from prior steps."
                    ),
                )
            )

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
        transcription_metadata=transcription_metadata,
        runtime_input_metadata=runtime_input_metadata,
    )


def _resolve_runtime_requested_ids(*, run: FlowRun, step: RuntimeStep) -> list[Any]:
    payload = run.input_payload_json or {}
    raw_step_inputs = payload.get("step_inputs")
    if isinstance(raw_step_inputs, dict):
        raw_step_input = raw_step_inputs.get(str(step.step_id)) or raw_step_inputs.get(step.step_id)
        if isinstance(raw_step_input, dict):
            return parse_requested_file_ids(raw_file_ids=raw_step_input.get("file_ids"))
    if step.step_order == 1:
        return parse_requested_file_ids(raw_file_ids=payload.get("file_ids"))
    return []


def _compose_runtime_and_chained_input(
    *,
    runtime_text: str,
    chained_text: str,
    replace_chain: bool,
) -> str:
    if replace_chain:
        return runtime_text
    segments = [segment.strip() for segment in (runtime_text, chained_text) if segment and segment.strip()]
    return "\n\n".join(segments)


def enforce_inline_input_cap(
    *,
    text: str,
    step_order: int,
    input_source: str,
    max_inline_text_bytes: int,
) -> None:
    if len(text.encode("utf-8")) <= max_inline_text_bytes:
        return
    raise TypedIOValidationException(
        f"Step {step_order}: resolved input for '{input_source}' exceeded max inline text bytes.",
        code="typed_io_input_too_large",
    )


def normalize_binding_text(value: str) -> str:
    return " ".join(value.split())


def is_legacy_mirrored_question_binding(
    *,
    question_template: str,
    interpolated_question: str,
    assistant_prompt_text: str | None,
) -> bool:
    if not isinstance(assistant_prompt_text, str) or assistant_prompt_text.strip() == "":
        return False
    prompt_normalized = normalize_binding_text(assistant_prompt_text)
    return (
        normalize_binding_text(question_template) == prompt_normalized
        or normalize_binding_text(interpolated_question) == prompt_normalized
    )


def resolve_input_source_text(
    *,
    input_source: str,
    run: FlowRun,
    step_order: int,
    prior_results: list[FlowStepResult],
    state: RunExecutionState | None = None,
    logger: Any,
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
