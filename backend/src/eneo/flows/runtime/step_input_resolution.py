from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Final, Sequence, cast
from uuid import UUID

from eneo.files.text import PDF_TEXT_LIKELY_REVERSED_WARNING, TextExtractor
from eneo.flows.domain.flow import FlowRun, FlowStepResult
from eneo.flows.domain.step_output import (
    OUTPUT_TEXT_OVERFLOW_KEY,
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_input_limits import DEFAULT_MAX_AUDIO_FILES_PER_RUN
from eneo.flows.flow_run_input_envelope import read_semantic_flow_input_payload
from eneo.flows.input_binding_contract_rules import (
    InputBindingContractError,
    effective_question_binding,
    item_template_field_names,
    question_binding,
    source_ref_bindings,
)
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime.input_files import load_files_by_requested_ids
from eneo.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepInputValue,
)
from eneo.flows.runtime.transcription_runtime import (
    AudioRuntimeDeps,
    AudioRuntimeRequest,
    resolve_transcribe_and_attach_audio_input,
)
from eneo.flows.runtime_input import build_runtime_input_config
from eneo.flows.template_reference_analyzer import (
    TemplateReference,
    analyze_template,
    consumes_runtime_input,
)
from eneo.main.exceptions import BadRequestException, TypedIOValidationException

RUNTIME_INPUT_SOURCE_HEADER_TEMPLATE: Final = "[SOURCE {source_number}]"
RUNTIME_INPUT_SOURCE_FILE_NAME_KEY: Final = "file_name"
RUNTIME_INPUT_SOURCE_EMPTY_TEXT_PLACEHOLDER: Final = "[no readable text extracted]"
RUNTIME_INPUT_SOURCE_EMPTY_TEXT_DIAGNOSTIC_CODE: Final = (
    "runtime_input_source_text_unavailable"
)


@dataclass(frozen=True)
class StepInputResolutionDeps:
    variable_resolver: Any
    resolve_http_input_source_text: Callable[
        ..., Awaitable[tuple[str, dict[str, Any] | list[Any] | None]]
    ]
    file_repo: Any
    principal: FlowPrincipal
    transcriber: Any | None
    space_repo: Any
    flow_run_repo: Any
    audit_service: Any | None
    actor: Any
    max_generic_files: int | None
    max_audio_files: int | None
    max_inline_text_bytes: int
    logger: Any


@dataclass(frozen=True)
class ResolvedSourceRefsInput:
    text: str
    reference_count: int
    template_reference_count: int


async def resolve_step_input(
    *,
    step: RuntimeStep,
    context: dict[str, Any],
    run: FlowRun,
    prior_results: list[FlowStepResult],
    state: RunExecutionState | None = None,
    version_metadata: dict[str, Any] | None = None,
    requested_file_ids: Sequence[UUID] = (),
    deps: StepInputResolutionDeps,
) -> StepInputValue:
    if step.step_order == 1 and step.input_source in {
        "previous_step",
        "all_previous_steps",
    }:
        raise TypedIOValidationException(
            "Step 1 cannot use previous_step/all_previous_steps input source. Use flow_input.",
            code=FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_POSITION.value,
        )
    if step.input_type == "json" and step.input_source == "all_previous_steps":
        raise TypedIOValidationException(
            f"Step {step.step_order}: input_type 'json' is incompatible with input_source "
            f"'all_previous_steps' (concatenated text is not valid JSON).",
            code=FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value,
        )
    if step.input_type == "audio" and step.input_source != "flow_input":
        raise TypedIOValidationException(
            f"Step {step.step_order}: input_type 'audio' is only supported with input_source 'flow_input'.",
            code=FlowApiErrorCode.TYPED_IO_AUDIO_SOURCE_UNSUPPORTED.value,
        )
    structured: dict[str, Any] | list[Any] | None = None
    if step.input_source == "http_get":
        source_text, structured = await deps.resolve_http_input_source_text(
            step=step,
            run=run,
            context=context,
        )
    else:
        source_text = resolve_input_source_text(
            input_source=step.input_source,
            input_type=step.input_type,
            run=run,
            step_order=step.step_order,
            prior_results=prior_results,
            state=state,
            logger=deps.logger,
        )
    input_text = source_text
    raw_extracted_text = ""
    used_question_binding = False
    diagnostics: list[StepDiagnostic] = []
    transcription_metadata: dict[str, Any] | None = None
    runtime_input_metadata: dict[str, Any] | None = None
    files = None
    runtime_input_config = build_runtime_input_config(step.input_config)
    runtime_input_text = ""
    requested_ids = list(requested_file_ids) if runtime_input_config.enabled else []

    if requested_ids:
        files = await _load_runtime_files(
            requested_ids=requested_ids,
            step_order=step.step_order,
            tenant_id=run.tenant_id,
            state=state,
            deps=deps,
        )

        if runtime_input_config.input_format == "audio":
            if deps.transcriber is None:
                raise TypedIOValidationException(
                    "Transcriber service is not available for audio input execution.",
                    code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED.value,
                )
            audio_request = AudioRuntimeRequest(
                run=run,
                step=step,
                context=context,
                version_metadata=version_metadata,
                files=files,
                requested_ids=requested_ids,
                max_audio_files=deps.max_audio_files or DEFAULT_MAX_AUDIO_FILES_PER_RUN,
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
            if audio_resolution.near_inline_limit_message is not None:
                diagnostics.append(
                    StepDiagnostic(
                        code="typed_io_transcript_near_limit",
                        message=audio_resolution.near_inline_limit_message,
                    )
                )
        else:
            runtime_input_text, file_text_diagnostics = _extract_text_from_files(
                files,
                step_order=step.step_order,
                logger=deps.logger,
            )
            diagnostics.extend(file_text_diagnostics)
            if runtime_input_text:
                raw_extracted_text = runtime_input_text

        runtime_input_metadata = _build_runtime_input_metadata(
            text=runtime_input_text,
            requested_ids=requested_ids,
            input_format=runtime_input_config.input_format,
            files=files,
            capture_mode="runtime_input",
        )

    bindings = step.input_bindings if isinstance(step.input_bindings, dict) else None
    if bindings is not None:
        source_refs_input = (
            _resolve_compose_source_refs_input(
                step=step,
                bindings=bindings,
                run=run,
                prior_results=prior_results,
                state=state,
                runtime_input_metadata=runtime_input_metadata,
                deps=deps,
            )
            if step.output_mode == "compose_text"
            else None
        )
        if source_refs_input is not None:
            input_text = source_refs_input.text
            used_question_binding = True
            diagnostics.append(
                StepDiagnostic(
                    code="flow_underlag_summary",
                    message=(
                        f"Resolved underlag from {source_refs_input.reference_count} "
                        f"source refs ({len(input_text.encode('utf-8'))} bytes)."
                    ),
                    severity="info",
                )
            )
        else:
            question_template = effective_question_binding(bindings)
            if question_template is not None:
                references = analyze_template(
                    question_template,
                    step_refs=state.step_ref_mapping if state is not None else {},
                    form_field_names=set(),
                )
                _raise_if_text_template_references_overflowed_output(
                    references=references,
                    prior_results=state.completed_by_order.values()
                    if state is not None
                    else prior_results,
                    consuming_step_order=step.step_order,
                    input_source="input_bindings.question",
                )
                interpolation_context = deps.variable_resolver.build_context(
                    run.input_payload_json,
                    prior_results,
                    current_step_order=step.step_order,
                    step_names_by_order=state.step_names_by_order if state else None,
                    step_ref_mapping=state.step_ref_mapping if state else None,
                    current_step_input=runtime_input_metadata,
                )
                interpolated_question = deps.variable_resolver.interpolate(
                    question_template,
                    interpolation_context,
                )
                input_text = interpolated_question
                used_question_binding = True
                diagnostics.append(
                    StepDiagnostic(
                        code="flow_underlag_summary",
                        message=(
                            f"Resolved underlag from {len(references)} template sources "
                            f"({len(interpolated_question.encode('utf-8'))} bytes)."
                        ),
                        severity="info",
                    )
                )
                if runtime_input_metadata is not None and not consumes_runtime_input(
                    references
                ):
                    raise TypedIOValidationException(
                        f"Step {step.step_order}: explicit runtime-input bindings must reference step_input.*",
                        code=FlowApiErrorCode.RUNTIME_INPUT_NOT_CONSUMED.value,
                    )

    if (
        runtime_input_config.enabled
        and runtime_input_metadata is not None
        and not used_question_binding
    ):
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
        if used_question_binding:
            # Explicit underlag is the complete LLM input; JSON normalization
            # may parse it for contracts, but must not replace it with source data.
            try:
                structured = json.loads(input_text)
            except (json.JSONDecodeError, ValueError):
                structured = None
        elif structured is not None:
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
        source_description = ""
        if step.input_source == "previous_step":
            has_substantive_input = bool(source_text.strip()) or (
                structured is not None and bool(input_text.strip())
            )
            source_description = f"step {step.step_order - 1} via previous_step"
        else:
            prior_source_count = 0
            prior_source_results = (
                state.completed_by_order.values() if state else prior_results
            )
            for pr in prior_source_results:
                if pr.step_order < step.step_order and isinstance(
                    pr.output_payload_json, dict
                ):
                    if str(pr.output_payload_json.get("text", "")).strip():
                        prior_source_count += 1
                        has_substantive_input = True
            prior_step_label = "step" if prior_source_count == 1 else "steps"
            source_description = (
                f"{prior_source_count} prior {prior_step_label} via all_previous_steps"
            )
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
        elif not used_question_binding:
            diagnostics.append(
                StepDiagnostic(
                    code="flow_underlag_summary",
                    message=(
                        f"Resolved implicit underlag from {source_description} "
                        f"({len(input_text.encode('utf-8'))} bytes of resolved input text)."
                    ),
                    severity="info",
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
        diagnostics=diagnostics,
        transcription_metadata=transcription_metadata,
        runtime_input_metadata=runtime_input_metadata,
    )


def _resolve_compose_source_refs_input(
    *,
    step: RuntimeStep,
    bindings: dict[str, Any],
    run: FlowRun,
    prior_results: list[FlowStepResult],
    state: RunExecutionState | None,
    runtime_input_metadata: dict[str, Any] | None,
    deps: StepInputResolutionDeps,
) -> ResolvedSourceRefsInput | None:
    try:
        source_refs = source_ref_bindings(bindings)
    except InputBindingContractError as exc:
        raise TypedIOValidationException(
            f"Step {step.step_order}: {exc}",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
        ) from exc
    if not source_refs:
        return None

    sections: list[str] = []
    template_reference_count = 0
    question_template = question_binding(bindings)
    if question_template is not None:
        references = analyze_template(
            question_template,
            step_refs=state.step_ref_mapping if state is not None else {},
            form_field_names=set(),
        )
        template_reference_count = len(references)
        _raise_if_text_template_references_overflowed_output(
            references=references,
            prior_results=state.completed_by_order.values()
            if state is not None
            else prior_results,
            consuming_step_order=step.step_order,
            input_source="input_bindings.question",
        )
        interpolation_context = deps.variable_resolver.build_context(
            run.input_payload_json,
            prior_results,
            current_step_order=step.step_order,
            step_names_by_order=state.step_names_by_order if state else None,
            step_ref_mapping=state.step_ref_mapping if state else None,
            current_step_input=runtime_input_metadata,
        )
        rendered_question = deps.variable_resolver.interpolate(
            question_template,
            interpolation_context,
        )
        if rendered_question.strip():
            sections.append(rendered_question)

    results_by_order = _prior_results_by_order(prior_results=prior_results, state=state)
    for ref in source_refs:
        referenced_order = _source_ref_step_order(ref.step_ref, state=state)
        if referenced_order is None:
            raise TypedIOValidationException(
                f"Step {step.step_order}: source_ref references unknown step '{ref.step_ref}'.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
            )
        result = results_by_order.get(referenced_order)
        if result is None:
            raise TypedIOValidationException(
                f"Step {step.step_order}: source_ref references unknown step '{ref.step_ref}'.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
            )
        value = _source_ref_runtime_value(
            ref_output=ref.output,
            field_path=ref.field_path,
            result=result,
            consuming_step_order=step.step_order,
        )
        rendered = _render_source_ref_value(
            value=value,
            item_template=ref.item_template,
            step_order=step.step_order,
        )
        if ref.label is not None and rendered.strip():
            rendered = f"{ref.label}:\n{rendered}"
        if rendered.strip():
            sections.append(rendered)

    return ResolvedSourceRefsInput(
        text="\n\n".join(sections),
        reference_count=len(source_refs),
        template_reference_count=template_reference_count,
    )


def _prior_results_by_order(
    *,
    prior_results: list[FlowStepResult],
    state: RunExecutionState | None,
) -> dict[int, FlowStepResult]:
    if state is not None:
        return dict(state.completed_by_order)
    return {result.step_order: result for result in prior_results}


def _source_ref_step_order(
    step_ref: str,
    *,
    state: RunExecutionState | None,
) -> int | None:
    if step_ref.startswith("step_"):
        step_number = step_ref.removeprefix("step_")
        if step_number.isdigit():
            return int(step_number)
    if state is not None:
        return state.step_ref_mapping.get(step_ref)
    return None


def _source_ref_runtime_value(
    *,
    ref_output: str,
    field_path: tuple[str, ...],
    result: FlowStepResult,
    consuming_step_order: int,
) -> Any:
    payload = (
        result.output_payload_json
        if isinstance(result.output_payload_json, dict)
        else {}
    )
    if ref_output == "text":
        return _read_complete_output_text(
            result,
            consuming_step_order=consuming_step_order,
            input_source="input_bindings.source_refs",
        )
    current: Any = payload.get("structured")
    for segment in field_path:
        if not isinstance(current, dict):
            raise TypedIOValidationException(
                f"Step {consuming_step_order}: source_ref field_path '{'.'.join(field_path)}' "
                "did not resolve through an object value.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
            )
        current_mapping = cast(dict[str, Any], current)
        if segment not in current_mapping:
            raise TypedIOValidationException(
                f"Step {consuming_step_order}: source_ref field_path '{'.'.join(field_path)}' "
                f"references missing field '{segment}'.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
            )
        current = current_mapping[segment]
    return current


def _render_source_ref_value(
    *,
    value: Any,
    item_template: str | None,
    step_order: int,
) -> str:
    if item_template is None:
        return _source_ref_value_to_text(value)
    if not isinstance(value, list):
        raise TypedIOValidationException(
            f"Step {step_order}: item_template source_ref resolved to a non-array value.",
            code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
        )
    rendered_items: list[str] = []
    field_names = item_template_field_names(item_template)
    for item_value in cast(list[object], value):
        if not isinstance(item_value, dict):
            raise TypedIOValidationException(
                f"Step {step_order}: item_template source_ref array contains a non-object item.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
            )
        item = cast(dict[str, Any], item_value)
        rendered = item_template
        for field_name in field_names:
            rendered = rendered.replace(
                "{" + field_name + "}",
                _source_ref_value_to_text(item.get(field_name)),
            )
        rendered_items.append(rendered.strip())
    return "\n\n".join(item for item in rendered_items if item)


def _source_ref_value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


async def _load_runtime_files(
    *,
    requested_ids: list[UUID],
    step_order: int,
    tenant_id: Any,
    state: RunExecutionState | None,
    deps: StepInputResolutionDeps,
) -> list[Any]:
    file_cache = state.file_cache if state else None
    files = await load_files_by_requested_ids(
        file_repo=deps.file_repo,
        requested_ids=requested_ids,
        principal=deps.principal,
        tenant_id=tenant_id,
        file_cache=file_cache,
    )
    returned_ids = {f.id for f in files}
    missing = [fid for fid in requested_ids if fid not in returned_ids]
    if missing:
        raise TypedIOValidationException(
            f"File(s) not found or not accessible: {missing}",
            code=FlowApiErrorCode.TYPED_IO_FILE_NOT_FOUND.value,
        )
    return files


def _extract_text_from_files(
    files: list[Any],
    *,
    step_order: int,
    logger: Any,
) -> tuple[str, list[StepDiagnostic]]:
    extracted: list[str] = []
    diagnostics: list[StepDiagnostic] = []
    for source_number, file in enumerate(files, start=1):
        text_value = getattr(file, "text", None)
        if not isinstance(text_value, str) or not text_value.strip():
            extracted.append(
                _format_runtime_source_text(
                    file=file,
                    source_number=source_number,
                    text=RUNTIME_INPUT_SOURCE_EMPTY_TEXT_PLACEHOLDER,
                )
            )
            diagnostics.append(
                _runtime_source_empty_text_diagnostic(
                    step_order=step_order,
                    source_number=source_number,
                    file=file,
                )
            )
            if logger is not None:
                logger.warning(
                    "flow_executor.runtime_input_source_text_unavailable "
                    "step_order=%d source_number=%d file_id=%s file_name=%s",
                    step_order,
                    source_number,
                    getattr(file, "id", None),
                    _runtime_source_file_name(file),
                )
            continue
        extracted.append(
            _format_runtime_source_text(
                file=file,
                source_number=source_number,
                text=text_value.strip(),
            )
        )
        for warning in _runtime_source_extraction_warnings(file=file, text=text_value):
            diagnostics.append(
                _runtime_source_extraction_warning_diagnostic(
                    step_order=step_order,
                    source_number=source_number,
                    file=file,
                    warning=warning,
                )
            )
            if logger is not None:
                logger.warning(
                    "flow_executor.runtime_input_source_extraction_warning "
                    "step_order=%d source_number=%d file_id=%s file_name=%s warning=%s",
                    step_order,
                    source_number,
                    getattr(file, "id", None),
                    _runtime_source_file_name(file),
                    warning,
                )
    return "\n\n".join(extracted), diagnostics


def _runtime_source_extraction_warnings(*, file: Any, text: str) -> list[str]:
    if getattr(file, "mimetype", None) != "application/pdf":
        return []
    return list(TextExtractor.pdf_text_quality_warnings(text))


def _runtime_source_extraction_warning_diagnostic(
    *,
    step_order: int,
    source_number: int,
    file: Any,
    warning: str,
) -> StepDiagnostic:
    source_label = RUNTIME_INPUT_SOURCE_HEADER_TEMPLATE.format(
        source_number=source_number
    )
    file_name = _runtime_source_file_name(file)
    source_description = (
        f"{source_label} ({file_name})" if file_name is not None else source_label
    )
    if warning == PDF_TEXT_LIKELY_REVERSED_WARNING:
        reason = "extracted PDF text looks reversed or garbled"
    else:
        reason = f"extracted text quality warning: {warning}"
    return StepDiagnostic(
        code=warning,
        message=f"Step {step_order}: {reason} for {source_description}.",
    )


def _runtime_source_empty_text_diagnostic(
    *,
    step_order: int,
    source_number: int,
    file: Any,
) -> StepDiagnostic:
    source_label = RUNTIME_INPUT_SOURCE_HEADER_TEMPLATE.format(
        source_number=source_number
    )
    file_name = _runtime_source_file_name(file)
    source_description = (
        f"{source_label} ({file_name})" if file_name is not None else source_label
    )
    return StepDiagnostic(
        code=RUNTIME_INPUT_SOURCE_EMPTY_TEXT_DIAGNOSTIC_CODE,
        message=(
            f"Step {step_order}: no readable text could be extracted from "
            f"{source_description}."
        ),
    )


def _format_runtime_source_text(*, file: Any, source_number: int, text: str) -> str:
    header_lines = [
        RUNTIME_INPUT_SOURCE_HEADER_TEMPLATE.format(source_number=source_number)
    ]
    file_name = _runtime_source_file_name(file)
    if file_name is not None:
        header_lines.append(f"{RUNTIME_INPUT_SOURCE_FILE_NAME_KEY}: {file_name}")
    header = "\n".join(header_lines)
    return f"{header}\n\n{text}"


def _runtime_source_file_name(file: Any) -> str | None:
    raw_name = getattr(file, "name", None)
    if not isinstance(raw_name, str):
        return None
    file_name = " ".join(raw_name.split())
    return file_name or None


def _build_runtime_input_metadata(
    *,
    text: str,
    requested_ids: list[UUID],
    input_format: str,
    files: list[Any],
    capture_mode: str,
) -> dict[str, Any]:
    file_metadata = [_build_runtime_file_metadata(file) for file in files]
    return {
        "text": text,
        "file_ids": [str(file_id) for file_id in requested_ids],
        "files_count": len(file_metadata),
        "files": file_metadata,
        "source_headers": [
            _build_runtime_source_header_metadata(
                file=file,
                source_number=source_number,
            )
            for source_number, file in enumerate(files, start=1)
        ],
        "total_file_size": sum(
            metadata["size"]
            for metadata in file_metadata
            if isinstance(metadata.get("size"), int)
        ),
        "extracted_text_length": len(text),
        "input_format": input_format,
        "capture_mode": capture_mode,
    }


def _build_runtime_source_header_metadata(
    *,
    file: Any,
    source_number: int,
) -> dict[str, Any]:
    file_name = _runtime_source_file_name(file)
    source_marker = RUNTIME_INPUT_SOURCE_HEADER_TEMPLATE.format(
        source_number=source_number
    )
    text_value = getattr(file, "text", None)
    extraction_warnings = (
        _runtime_source_extraction_warnings(file=file, text=text_value)
        if isinstance(text_value, str)
        else []
    )
    return {
        "source_number": source_number,
        "source_label": file_name or source_marker,
        "source_marker": source_marker,
        "file_id": str(getattr(file, "id")),
        "file_name": file_name,
        "has_file_name": file_name is not None,
        "has_text": isinstance(text_value, str) and text_value.strip() != "",
        "text_length": len(text_value) if isinstance(text_value, str) else None,
        "extraction_warnings": extraction_warnings,
    }


def _build_runtime_file_metadata(file: Any) -> dict[str, Any]:
    raw_file_type = getattr(file, "file_type", None)
    if isinstance(raw_file_type, Enum):
        file_type = raw_file_type.value
    elif isinstance(raw_file_type, str):
        file_type = raw_file_type
    else:
        file_type = None
    text_value = getattr(file, "text", None)
    transcription_value = getattr(file, "transcription", None)
    extraction_warnings = (
        _runtime_source_extraction_warnings(file=file, text=text_value)
        if isinstance(text_value, str)
        else []
    )
    return {
        "id": str(getattr(file, "id")),
        "name": getattr(file, "name", None),
        "checksum": getattr(file, "checksum", None),
        "size": getattr(file, "size", None),
        "mimetype": getattr(file, "mimetype", None),
        "file_type": file_type,
        "text_length": len(text_value) if isinstance(text_value, str) else None,
        "has_text": isinstance(text_value, str) and text_value.strip() != "",
        "has_transcription": (
            isinstance(transcription_value, str) and transcription_value.strip() != ""
        ),
        "extraction_warnings": extraction_warnings,
    }


def _compose_runtime_and_chained_input(
    *,
    runtime_text: str,
    chained_text: str,
    replace_chain: bool,
) -> str:
    if replace_chain:
        return runtime_text
    segments = [
        segment.strip()
        for segment in (runtime_text, chained_text)
        if segment and segment.strip()
    ]
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
        code=FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value,
    )


def resolve_input_source_text(
    *,
    input_source: str,
    input_type: str = "text",
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
        semantic_payload = read_semantic_flow_input_payload(run.input_payload_json)
        if not semantic_payload:
            return ""
        return json.dumps(semantic_payload, ensure_ascii=False)
    if input_source == "previous_step":
        previous = next(
            (item for item in prior_results if item.step_order == step_order - 1), None
        )
        if previous and isinstance(previous.output_payload_json, dict):
            if not _can_read_structured_output(previous, input_type=input_type):
                text = _read_complete_output_text(
                    previous,
                    consuming_step_order=step_order,
                    input_source=input_source,
                )
            else:
                text = str(previous.output_payload_json.get("text", ""))
            if not text.strip():
                logger.warning(
                    "flow_executor.empty_previous_step_input run_id=%s step_order=%d "
                    "previous_step_order=%d reason=previous_output_text_empty",
                    run.id,
                    step_order,
                    step_order - 1,
                )
            return text
        logger.warning(
            "flow_executor.empty_previous_step_input run_id=%s step_order=%d "
            "previous_step_order=%d reason=%s",
            run.id,
            step_order,
            step_order - 1,
            "no_previous_result" if previous is None else "output_not_dict",
        )
        return ""
    if input_source == "all_previous_steps":
        if state:
            _raise_if_any_prior_output_text_overflowed(
                prior_results=state.completed_by_order.values(),
                consuming_step_order=step_order,
                input_source=input_source,
            )
            return state.all_previous_text_before(step_order)
        _raise_if_any_prior_output_text_overflowed(
            prior_results=prior_results,
            consuming_step_order=step_order,
            input_source=input_source,
        )
        parts: list[str] = []
        for previous in sorted(prior_results, key=lambda item: item.step_order):
            if previous.step_order >= step_order:
                continue
            text = _read_complete_output_text(
                previous,
                consuming_step_order=step_order,
                input_source=input_source,
            )
            parts.append(
                f"<step_{previous.step_order}_output>\n{text}\n</step_{previous.step_order}_output>"
            )
        return "\n".join(parts)
    if input_source == "http_get":
        raise BadRequestException(
            f"Input source '{input_source}' is not yet supported in runtime execution."
        )
    raise BadRequestException(f"Unsupported input source '{input_source}'.")


def _raise_if_text_template_references_overflowed_output(
    *,
    references: Sequence[TemplateReference],
    prior_results: Iterable[FlowStepResult],
    consuming_step_order: int,
    input_source: str,
) -> None:
    results_by_order = {
        result.step_order: result
        for result in prior_results
        if result.step_order < consuming_step_order
    }
    for reference in references:
        if reference.tail not in {"output", "output.text"}:
            continue
        referenced_step_order = reference.step_order
        if referenced_step_order is None:
            continue
        result = results_by_order.get(referenced_step_order)
        if result is None:
            continue
        _raise_if_output_text_overflowed(
            result,
            consuming_step_order=consuming_step_order,
            input_source=input_source,
        )


def _raise_if_any_prior_output_text_overflowed(
    *,
    prior_results: Iterable[FlowStepResult],
    consuming_step_order: int,
    input_source: str,
) -> None:
    for result in prior_results:
        if result.step_order >= consuming_step_order:
            continue
        _raise_if_output_text_overflowed(
            result,
            consuming_step_order=consuming_step_order,
            input_source=input_source,
        )


def _can_read_structured_output(result: FlowStepResult, *, input_type: str) -> bool:
    if input_type != "json":
        return False
    payload = result.output_payload_json
    if not isinstance(payload, dict):
        return False
    return isinstance(payload.get("structured"), (dict, list))


def _raise_if_output_text_overflowed(
    result: FlowStepResult,
    *,
    consuming_step_order: int,
    input_source: str,
) -> None:
    _read_complete_output_text(
        result,
        consuming_step_order=consuming_step_order,
        input_source=input_source,
    )


def _read_complete_output_text(
    result: FlowStepResult,
    *,
    consuming_step_order: int,
    input_source: str,
) -> str:
    payload = result.output_payload_json
    if not isinstance(payload, dict) or (
        "text" not in payload and OUTPUT_TEXT_OVERFLOW_KEY not in payload
    ):
        return ""
    try:
        text = interpret_step_text(payload)
    except StepOutputMetadataError as exc:
        raise TypedIOValidationException(
            f"Step {consuming_step_order}: input_source '{input_source}' cannot "
            f"consume malformed persisted text from step {result.step_order}.",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        ) from exc
    if isinstance(text, FileBackedStepText):
        raise TypedIOValidationException(
            f"Step {consuming_step_order}: input_source '{input_source}' cannot "
            f"consume step {result.step_order} text because that output exceeded "
            "inline storage and was stored as a generated output file.",
            code=FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value,
        )
    return text.text
