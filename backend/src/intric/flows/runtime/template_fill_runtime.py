from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from intric.files.file_models import FileCreate, FileType
from intric.files.file_repo import FileRepository
from intric.flows.flow import FlowRun, FlowStepResultStatus
from intric.flows.runtime.docx_template_runtime import extract_docx_text, render_docx_template
from intric.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
)
from intric.flows.variable_resolver import FlowVariableResolver
from intric.main.exceptions import BadRequestException, TypedIOValidationException


_STEP_REFERENCE_PATTERN = re.compile(r"step_(\d+)")


ApplyOutputCap = Callable[[str, FlowRun, RuntimeStep], Awaitable[tuple[str, list[UUID]]]]


@dataclass(frozen=True)
class TemplateFillRuntimeDeps:
    variable_resolver: FlowVariableResolver
    file_repo: FileRepository
    template_asset_service: Any
    apply_output_cap: ApplyOutputCap
    user_id: UUID
    logger: logging.Logger


async def execute_template_fill_step(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    deps: TemplateFillRuntimeDeps,
) -> StepExecutionOutput:
    current_stage = "parsing template configuration"
    try:
        (
            template_asset_id,
            template_file_id,
            template_checksum,
            template_name,
            placeholders,
            bindings,
        ) = _parse_template_output_config(step)
        deps.logger.info(
            "flow_executor.template_fill.start run_id=%s step_order=%d template_asset_id=%s template_file_id=%s placeholders=%d",
            run.id,
            step.step_order,
            template_asset_id,
            template_file_id,
            len(bindings),
        )

        current_stage = "loading the published DOCX template"
        template_file = await _load_template_file(
            template_asset_service=deps.template_asset_service,
            file_repo=deps.file_repo,
            tenant_id=run.tenant_id,
            template_asset_id=template_asset_id,
            template_file_id=template_file_id,
            template_checksum=template_checksum,
        )
        template_blob = template_file.blob
        if template_blob is None:  # defensive narrowing; _load_template_file already rejects this
            raise TypedIOValidationException(
                "The published DOCX template could not be read because the saved file content is missing. Re-upload the template and publish the flow again.",
                code="typed_io_template_render_failed",
            )
        deps.logger.debug(
            "flow_executor.template_fill.template_loaded run_id=%s step_order=%d template_file_id=%s size=%d checksum=%s",
            run.id,
            step.step_order,
            template_file_id,
            len(template_blob),
            template_file.checksum,
        )

        current_stage = "resolving template bindings"
        resolved_bindings = _resolve_template_bindings(
            variable_resolver=deps.variable_resolver,
            step=step,
            run=run,
            state=state,
            bindings=bindings,
        )
        persisted_text = _build_template_fill_summary(
            placeholders=placeholders,
            resolved_bindings=resolved_bindings,
        )
        deps.logger.debug(
            "flow_executor.template_fill.bindings_resolved run_id=%s step_order=%d template_file_id=%s placeholders=%s",
            run.id,
            step.step_order,
            template_file_id,
            ",".join(sorted(resolved_bindings)),
        )

        current_stage = "rendering the DOCX template"
        blob, mimetype, filename = render_docx_template(
            template_bytes=template_blob,
            context=resolved_bindings,
            step_order=step.step_order,
        )
        deps.logger.debug(
            "flow_executor.template_fill.template_rendered run_id=%s step_order=%d template_file_id=%s filename=%s size=%d",
            run.id,
            step.step_order,
            template_file_id,
            filename,
            len(blob),
        )
    except TypedIOValidationException as exc:
        deps.logger.info(
            "flow_executor.template_fill.validation_failed run_id=%s step_order=%d stage=%s code=%s message=%s",
            run.id,
            step.step_order,
            current_stage,
            exc.code,
            str(exc),
        )
        raise
    except Exception as exc:
        deps.logger.exception(
            "flow_executor.template_fill.stage_failed run_id=%s step_order=%d stage=%s",
            run.id,
            step.step_order,
            current_stage,
        )
        raise _template_fill_runtime_error(stage=current_stage, exc=exc) from exc

    try:
        stored_file = await deps.file_repo.add(
            FileCreate(
                file_type=FileType.DOCUMENT,
                blob=blob,
                name=filename,
                mimetype=mimetype,
                checksum=hashlib.sha256(blob).hexdigest(),
                size=len(blob),
                user_id=deps.user_id,
                tenant_id=run.tenant_id,
            )
        )
    except Exception as exc:
        deps.logger.exception(
            "flow_executor.template_fill.stage_failed run_id=%s step_order=%d stage=save_generated_docx template_file_id=%s",
            run.id,
            step.step_order,
            template_file_id,
        )
        raise _template_fill_runtime_error(stage="saving the generated DOCX", exc=exc) from exc

    try:
        rendered_text = extract_docx_text(blob)
    except Exception as exc:
        deps.logger.exception(
            "flow_executor.template_fill.stage_failed run_id=%s step_order=%d stage=read_generated_docx template_file_id=%s generated_file_id=%s",
            run.id,
            step.step_order,
            template_file_id,
            stored_file.id,
        )
        raise _template_fill_runtime_error(stage="reading the generated DOCX", exc=exc) from exc

    bindings_text = json.dumps(resolved_bindings, ensure_ascii=False, sort_keys=True)

    deps.logger.info(
        "flow_executor.template_fill.completed run_id=%s step_order=%d template_file_id=%s generated_file_id=%s text_length=%d",
        run.id,
        step.step_order,
        template_file_id,
        stored_file.id,
        len(rendered_text),
    )

    return StepExecutionOutput(
        input_text=bindings_text,
        source_text=bindings_text,
        input_source=step.input_source,
        used_question_binding=False,
        legacy_prompt_binding_used=False,
        full_text=rendered_text,
        persisted_text=persisted_text,
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=0,
        num_tokens_output=0,
        effective_prompt="",
        model_parameters_json={
            "mode": "template_fill",
            "template_file_id": str(template_file_id),
            "template_asset_id": str(template_asset_id) if template_asset_id is not None else None,
            "template_checksum": template_checksum,
        },
        structured_output=None,
        artifacts=[
            {
                "file_id": str(stored_file.id),
                "name": filename,
                "mimetype": mimetype,
                "size": len(blob),
            }
        ],
        diagnostics=[
            StepDiagnostic(
                code="template_fill_used",
                message=(
                    f"Step {step.step_order}: template_fill mode rendered a DOCX template without calling the assistant."
                ),
                severity="info",
            )
        ],
        output_payload_extensions={
            "template_provenance": {
                "template_name": template_name or template_file.name,
                "template_asset_id": str(template_asset_id) if template_asset_id is not None else None,
                "template_file_id": str(template_file_id),
                "template_checksum": template_checksum,
                "published_flow_version": run.flow_version,
            },
            "template_fill_debug": {
                "rendered_docx_text_raw": rendered_text,
                "summary_mode": "resolved_bindings",
                "placeholder_count": len(placeholders),
            }
        },
    )


def _parse_template_output_config(
    step: RuntimeStep,
) -> tuple[UUID | None, UUID, str | None, str | None, list[str], dict[str, str]]:
    if not isinstance(step.output_config, dict):
        raise TypedIOValidationException(
            "Template fill requires output_config.",
            code="typed_io_template_render_failed",
        )

    template_asset_id_raw = step.output_config.get("template_asset_id")
    template_asset_id: UUID | None = None
    if template_asset_id_raw not in (None, ""):
        try:
            template_asset_id = UUID(str(template_asset_id_raw))
        except Exception as exc:
            raise TypedIOValidationException(
                "Template fill requires a valid template_asset_id.",
                code="typed_io_template_render_failed",
            ) from exc

    template_file_id_raw = step.output_config.get("template_file_id")
    try:
        template_file_id = UUID(str(template_file_id_raw))
    except Exception as exc:
        raise TypedIOValidationException(
            "Template fill requires a valid template_file_id.",
            code="typed_io_template_render_failed",
        ) from exc

    bindings_raw = cast(dict[Any, Any] | None, step.output_config.get("bindings"))
    placeholders_raw = cast(list[Any] | None, step.output_config.get("placeholders"))
    if not isinstance(bindings_raw, dict):
        raise TypedIOValidationException(
            "Template fill requires output_config.bindings.",
            code="typed_io_template_render_failed",
        )

    bindings: dict[str, str] = {}
    for placeholder, expression in bindings_raw.items():
        if not isinstance(placeholder, str):
            continue
        if not isinstance(expression, str):
            raise TypedIOValidationException(
                f"Template binding '{placeholder}' must be a string expression.",
                code="typed_io_template_render_failed",
            )
        bindings[placeholder] = expression
    placeholders: list[str] = []
    if isinstance(placeholders_raw, list):
        for raw_placeholder in placeholders_raw:
            if isinstance(raw_placeholder, str):
                placeholder = raw_placeholder.strip()
                if placeholder and placeholder not in placeholders:
                    placeholders.append(placeholder)
    for placeholder in bindings:
        if placeholder not in placeholders:
            placeholders.append(placeholder)

    return (
        template_asset_id,
        template_file_id,
        _optional_string(step.output_config.get("template_checksum")),
        _optional_string(step.output_config.get("template_name")),
        placeholders,
        bindings,
    )


async def _load_template_file(
    *,
    template_asset_service: Any,
    file_repo: FileRepository,
    tenant_id: UUID,
    template_asset_id: UUID | None,
    template_file_id: UUID,
    template_checksum: str | None,
):
    if template_asset_id is not None:
        try:
            asset, template_file = await template_asset_service.get_published_template_file(
                tenant_id=tenant_id,
                asset_id=template_asset_id,
                expected_checksum=template_checksum,
            )
        except Exception as exc:
            raise TypedIOValidationException(
                "The published DOCX template asset is no longer available. Re-publish the flow with a current template.",
                code="flow_template_not_accessible",
            ) from exc
        if asset.file_id != template_file_id:
            raise TypedIOValidationException(
                "The published DOCX template asset no longer matches the pinned template file. Re-publish the flow.",
                code="flow_template_not_accessible",
            )
        return template_file

    files = await file_repo.get_list_by_id_and_tenant(
        ids=[template_file_id],
        tenant_id=tenant_id,
        include_transcription=False,
    )
    if not files:
        raise TypedIOValidationException(
            "Published DOCX template file was not found.",
            code="typed_io_template_render_failed",
        )
    template_file = files[0]
    if template_file.blob is None:
        raise TypedIOValidationException(
            "The published DOCX template could not be read because the saved file content is missing. Re-upload the template and publish the flow again.",
            code="typed_io_template_render_failed",
        )
    if template_checksum and template_file.checksum != template_checksum:
        raise TypedIOValidationException(
            "Published DOCX template checksum no longer matches the saved flow version.",
            code="typed_io_template_checksum_mismatch",
        )
    return template_file


def _resolve_template_bindings(
    *,
    variable_resolver: FlowVariableResolver,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    bindings: dict[str, str],
) -> dict[str, str]:
    context = variable_resolver.build_context(
        run.input_payload_json,
        state.prior_results,
        current_step_order=step.step_order,
        step_names_by_order=state.step_names_by_order,
    )
    resolved: dict[str, str] = {}
    for placeholder, expression in bindings.items():
        if not expression.strip():
            resolved[placeholder] = ""
            continue
        try:
            resolved[placeholder] = variable_resolver.interpolate(expression, context)
        except BadRequestException as exc:
            failed_step_order = _failed_step_order_for_expression(
                expression=expression,
                prior_results=state.prior_results,
            )
            if failed_step_order is not None:
                raise TypedIOValidationException(
                    f"Template binding '{placeholder}' could not be resolved because step {failed_step_order} failed earlier in the run.",
                    code="typed_io_template_render_failed",
                ) from exc
            raise TypedIOValidationException(
                f"Template binding '{placeholder}' could not be resolved: {exc}",
                code="typed_io_template_render_failed",
            ) from exc
    return resolved


def _build_template_fill_summary(
    *,
    placeholders: list[str],
    resolved_bindings: dict[str, str],
) -> str:
    sections: list[str] = []
    for placeholder in placeholders:
        body = _strip_leading_placeholder_heading(
            placeholder=placeholder,
            body=resolved_bindings.get(placeholder, ""),
        )
        section = f"## {placeholder}"
        if body:
            section = f"{section}\n\n{body}"
        sections.append(section)
    return "\n\n".join(sections)


def _strip_leading_placeholder_heading(*, placeholder: str, body: str) -> str:
    stripped = body.lstrip()
    if not stripped:
        return ""

    lines = stripped.splitlines()
    if not lines:
        return stripped

    first_line = lines[0].strip()
    if not first_line:
        return stripped

    normalized_heading = first_line.lstrip("#").strip().rstrip(":").strip()
    if _normalize_placeholder_token(normalized_heading) != _normalize_placeholder_token(placeholder):
        return body

    remainder = "\n".join(lines[1:]).lstrip()
    return remainder


def _normalize_placeholder_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _failed_step_order_for_expression(
    *,
    expression: str,
    prior_results: list[Any],
) -> int | None:
    match = _STEP_REFERENCE_PATTERN.search(expression)
    if match is None:
        return None
    step_order = int(match.group(1))
    for result in prior_results:
        if result.step_order != step_order:
            continue
        if result.status != FlowStepResultStatus.COMPLETED:
            return step_order
    return None


def _template_fill_runtime_error(*, stage: str, exc: Exception) -> TypedIOValidationException:
    return TypedIOValidationException(
        f"DOCX template assembly failed while {stage}. Check the published template asset and try again.",
        code="typed_io_template_render_failed",
    )
