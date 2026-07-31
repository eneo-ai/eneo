from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_models import File, FileType
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.flows.domain.flow import FlowRun, FlowStepResultStatus
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
    merge_resolved_input_edges,
)
from eneo.flows.flow_template_asset_repo import FlowTemplateAssetRepository
from eneo.flows.runtime.docx_template_runtime import (
    extract_docx_text,
    render_docx_template,
)
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    TypedIOValidationException,
)

_STEP_REFERENCE_PATTERN = re.compile(r"step_(\d+)")
_FULL_TEMPLATE_EXPRESSION_PATTERN = re.compile(r"^\s*\{\{\s*([^{}]+)\s*\}\}\s*$")


@dataclass(frozen=True)
class TemplateFillRuntimeDeps:
    variable_resolver: FlowVariableResolver
    file_repo: FileRepository
    file_content_loader: FileContentLoader
    file_service: FileService
    template_asset_repo: FlowTemplateAssetRepository
    logger: logging.Logger


@dataclass(frozen=True)
class PreparedTemplateFillStep:
    template_asset_id: UUID
    template_checksum: str | None
    template_name: str | None
    template_file_id: UUID
    template_file_name: str
    template_blob: bytes
    placeholders: tuple[str, ...]
    resolved_bindings: dict[str, str]
    persisted_text: str
    resolved_input_edges: tuple[FlowResolvedInputEdge, ...]


@dataclass(frozen=True)
class ResolvedTemplateBindings:
    values: dict[str, str]
    edges: tuple[FlowResolvedInputEdge, ...]


async def prepare_template_fill_step(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    deps: TemplateFillRuntimeDeps,
) -> PreparedTemplateFillStep:
    current_stage = "parsing template configuration"
    try:
        (
            template_asset_id,
            template_checksum,
            template_name,
            placeholders,
            bindings,
        ) = _parse_template_output_config(step)
        deps.logger.info(
            "flow_executor.template_fill.start run_id=%s step_order=%d template_asset_id=%s placeholders=%d",
            run.id,
            step.step_order,
            template_asset_id,
            len(bindings),
        )

        current_stage = "loading the published DOCX template"
        template_file = await _load_template_file(
            template_asset_repo=deps.template_asset_repo,
            file_repo=deps.file_repo,
            file_content_loader=deps.file_content_loader,
            tenant_id=run.tenant_id,
            template_asset_id=template_asset_id,
            template_checksum=template_checksum,
        )
        template_blob = template_file.blob
        if template_blob is None:
            raise TypedIOValidationException(
                "The published DOCX template could not be read because the saved file content is missing. Re-upload the template and publish the flow again.",
                code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
            )
        deps.logger.debug(
            "flow_executor.template_fill.template_loaded run_id=%s step_order=%d template_file_id=%s size=%d checksum=%s",
            run.id,
            step.step_order,
            template_file.id,
            len(template_blob),
            template_file.checksum,
        )

        current_stage = "resolving template bindings"
        resolved = _resolve_template_bindings(
            variable_resolver=deps.variable_resolver,
            step=step,
            run=run,
            state=state,
            bindings=bindings,
        )
        persisted_text = _build_template_fill_summary(
            placeholders=placeholders,
            resolved_bindings=resolved.values,
        )
        deps.logger.debug(
            "flow_executor.template_fill.bindings_resolved run_id=%s step_order=%d template_file_id=%s placeholders=%s",
            run.id,
            step.step_order,
            template_file.id,
            ",".join(sorted(resolved.values)),
        )
        return PreparedTemplateFillStep(
            template_asset_id=template_asset_id,
            template_checksum=template_checksum,
            template_name=template_name,
            template_file_id=template_file.id,
            template_file_name=template_file.name,
            template_blob=template_blob,
            placeholders=tuple(placeholders),
            resolved_bindings=resolved.values,
            persisted_text=persisted_text,
            resolved_input_edges=resolved.edges,
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


async def complete_template_fill_step(
    *,
    step: RuntimeStep,
    run: FlowRun,
    prepared: PreparedTemplateFillStep,
    deps: TemplateFillRuntimeDeps,
) -> StepExecutionOutput:
    current_stage = "rendering the DOCX template"
    try:
        blob, mimetype, filename = render_docx_template(
            template_bytes=prepared.template_blob,
            context=prepared.resolved_bindings,
            step_order=step.step_order,
        )
        deps.logger.debug(
            "flow_executor.template_fill.template_rendered run_id=%s step_order=%d template_file_id=%s filename=%s size=%d",
            run.id,
            step.step_order,
            prepared.template_file_id,
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
        output_checksum = hashlib.sha256(blob).hexdigest()
        stored_file = await deps.file_service.save_generated_file(
            payload=blob,
            name=filename,
            mimetype=mimetype,
            file_type=FileType.DOCUMENT,
        )
    except Exception as exc:
        deps.logger.exception(
            "flow_executor.template_fill.stage_failed run_id=%s step_order=%d stage=save_generated_docx template_file_id=%s",
            run.id,
            step.step_order,
            prepared.template_file_id,
        )
        raise _template_fill_runtime_error(
            stage="saving the generated DOCX", exc=exc
        ) from exc

    try:
        rendered_text = extract_docx_text(blob)
    except Exception as exc:
        deps.logger.exception(
            "flow_executor.template_fill.stage_failed run_id=%s step_order=%d stage=read_generated_docx template_file_id=%s generated_file_id=%s",
            run.id,
            step.step_order,
            prepared.template_file_id,
            stored_file.id,
        )
        raise _template_fill_runtime_error(
            stage="reading the generated DOCX", exc=exc
        ) from exc

    bindings_text = json.dumps(
        prepared.resolved_bindings,
        ensure_ascii=False,
        sort_keys=True,
    )

    deps.logger.info(
        "flow_executor.template_fill.completed run_id=%s step_order=%d template_file_id=%s generated_file_id=%s text_length=%d",
        run.id,
        step.step_order,
        prepared.template_file_id,
        stored_file.id,
        len(rendered_text),
    )

    template_name_value = prepared.template_name or prepared.template_file_name
    output_payload_extensions: dict[str, Any] = {
        "template_fill_debug": {
            "rendered_docx_text_raw": rendered_text,
            "summary_mode": "resolved_bindings",
            "placeholder_count": len(prepared.placeholders),
        }
    }
    output_payload_extensions["template_provenance"] = {
        "template_name": template_name_value,
        "template_asset_id": str(prepared.template_asset_id),
        "template_file_id": str(prepared.template_file_id),
        "template_checksum": prepared.template_checksum,
        "published_flow_version": run.flow_version,
    }

    return StepExecutionOutput(
        input_text=bindings_text,
        source_text=bindings_text,
        input_source=step.input_source,
        used_question_binding=False,
        full_text=rendered_text,
        persisted_text=prepared.persisted_text,
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=0,
        num_tokens_output=0,
        effective_prompt="",
        model_parameters_json={
            "mode": "template_fill",
            "template_file_id": str(prepared.template_file_id),
            "template_asset_id": str(prepared.template_asset_id),
            "template_checksum": prepared.template_checksum,
        },
        structured_output=None,
        artifacts=[
            {
                "file_id": str(stored_file.id),
                "name": filename,
                "mimetype": mimetype,
                "size": len(blob),
                "checksum": getattr(stored_file, "checksum", None) or output_checksum,
                "file_type": "document",
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
        output_payload_extensions=output_payload_extensions,
    )


def _parse_template_output_config(
    step: RuntimeStep,
) -> tuple[UUID, str | None, str | None, list[str], dict[str, str]]:
    if not isinstance(step.output_config, dict):
        raise TypedIOValidationException(
            "Template fill requires output_config.",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )

    template_asset_id_raw = step.output_config.get("template_asset_id")
    if template_asset_id_raw in (None, ""):
        raise TypedIOValidationException(
            "Template fill requires a valid template_asset_id.",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )
    try:
        template_asset_id = UUID(str(template_asset_id_raw))
    except Exception as exc:
        raise TypedIOValidationException(
            "Template fill requires a valid template_asset_id.",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        ) from exc

    if step.output_config.get("template_file_id") not in (None, ""):
        raise TypedIOValidationException(
            "Template fill output_config.template_file_id is not supported; use template_asset_id.",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )

    bindings_raw = cast(dict[Any, Any] | None, step.output_config.get("bindings"))
    placeholders_raw = cast(list[Any] | None, step.output_config.get("placeholders"))
    if not isinstance(bindings_raw, dict):
        raise TypedIOValidationException(
            "Template fill requires output_config.bindings.",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
        )

    bindings: dict[str, str] = {}
    for placeholder, expression in bindings_raw.items():
        if not isinstance(placeholder, str):
            continue
        if not isinstance(expression, str):
            raise TypedIOValidationException(
                f"Template binding '{placeholder}' must be a string expression.",
                code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
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
        _optional_string(step.output_config.get("template_checksum")),
        _optional_string(step.output_config.get("template_name")),
        placeholders,
        bindings,
    )


async def _load_template_file(
    *,
    template_asset_repo: FlowTemplateAssetRepository,
    file_repo: FileRepository,
    file_content_loader: FileContentLoader,
    tenant_id: UUID,
    template_asset_id: UUID,
    template_checksum: str | None,
) -> File:
    try:
        asset = await template_asset_repo.get(
            asset_id=template_asset_id,
            tenant_id=tenant_id,
        )
    except NotFoundException as exc:
        raise TypedIOValidationException(
            "The published DOCX template asset is no longer available. Re-publish the flow with a current template.",
            code=FlowApiErrorCode.TEMPLATE_NOT_ACCESSIBLE.value,
        ) from exc

    try:
        metadata = await file_repo.get_by_id(
            file_id=asset.file_id,
            tenant_id=tenant_id,
        )
        template_file = (await file_content_loader.load([metadata]))[metadata.id]
    except NotFoundException:
        raise TypedIOValidationException(
            "The published DOCX template asset file is no longer available. Re-publish the flow with a current template.",
            code=FlowApiErrorCode.TEMPLATE_NOT_ACCESSIBLE.value,
        )
    if template_file.blob is None:
        raise TypedIOValidationException(
            "The published DOCX template could not be read because the saved file content is missing. Re-upload the template and publish the flow again.",
            code=FlowApiErrorCode.TEMPLATE_MISSING_CONTENT.value,
        )
    if template_checksum and template_file.checksum != template_checksum:
        raise TypedIOValidationException(
            "Published DOCX template checksum no longer matches the saved flow version.",
            code=FlowApiErrorCode.TYPED_IO_TEMPLATE_CHECKSUM_MISMATCH.value,
        )
    return template_file


def _resolve_template_bindings(
    *,
    variable_resolver: FlowVariableResolver,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    bindings: dict[str, str],
) -> ResolvedTemplateBindings:
    context = variable_resolver.build_context_with_evidence(
        run.input_payload_json,
        state.prior_results,
        current_step_order=step.step_order,
        step_names_by_order=state.step_names_by_order,
        step_ref_mapping=state.step_ref_mapping,
    )
    resolved: dict[str, str] = {}
    edges: list[FlowResolvedInputEdge] = []
    for placeholder, expression in bindings.items():
        if not expression.strip():
            resolved[placeholder] = ""
            continue
        try:
            interpolation = variable_resolver.interpolate_with_evidence(
                expression,
                context,
                binding_ref=f"output_config.bindings.{placeholder}",
            )
            match = _FULL_TEMPLATE_EXPRESSION_PATTERN.fullmatch(expression)
            if match is not None:
                # Evidence hashes the raw value, while template fill preserves compact
                # JSON for bindings that consist of one complete expression.
                raw_value = variable_resolver.resolve_path(
                    context, match.group(1).strip()
                )
                resolved[placeholder] = _stringify_template_binding_value(raw_value)
            else:
                resolved[placeholder] = interpolation.text
            edges.extend(interpolation.edges)
        except BadRequestException as exc:
            failed_step_order = _failed_step_order_for_expression(
                expression=expression,
                prior_results=state.prior_results,
            )
            if failed_step_order is not None:
                raise TypedIOValidationException(
                    f"Template binding '{placeholder}' could not be resolved because step {failed_step_order} failed earlier in the run.",
                    code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
                ) from exc
            raise TypedIOValidationException(
                f"Template binding '{placeholder}' could not be resolved: {exc}",
                code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
            ) from exc
    return ResolvedTemplateBindings(
        values=resolved,
        edges=merge_resolved_input_edges(edges),
    )


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
    if _normalize_placeholder_token(normalized_heading) != _normalize_placeholder_token(
        placeholder
    ):
        return body

    remainder = "\n".join(lines[1:]).lstrip()
    return remainder


def _normalize_placeholder_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _stringify_template_binding_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


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


def _template_fill_runtime_error(
    *, stage: str, exc: Exception
) -> TypedIOValidationException:
    return TypedIOValidationException(
        f"DOCX template assembly failed while {stage}. Check the published template asset and try again.",
        code=FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED.value,
    )
