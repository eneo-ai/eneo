from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from intric.files.file_models import FileCreate, FileType


class RuntimeOutputStep(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def output_type(self) -> str: ...

    @property
    def output_contract(self) -> dict[str, Any] | None: ...


class RuntimeOutputRun(Protocol):
    @property
    def tenant_id(self) -> Any: ...


class ValidateAgainstContractFn(Protocol):
    def __call__(
        self,
        data: Any,
        schema: dict[str, Any],
        *,
        label: str,
    ) -> None: ...


class RenderDocumentFn(Protocol):
    def __call__(
        self,
        text: str,
        output_type: str,
        *,
        step_order: int,
    ) -> tuple[bytes, str, str]: ...


@dataclass(frozen=True)
class OutputRuntimeDeps:
    file_repo: Any
    user_id: Any
    compile_validators: Callable[[list[Any]], dict[tuple[str, int], Any]]
    parse_json_output: Callable[[str], dict[str, Any] | list[Any]]
    validate_against_contract: ValidateAgainstContractFn
    render_document: RenderDocumentFn


async def process_typed_output(
    *,
    full_text: str,
    step: RuntimeOutputStep,
    run: RuntimeOutputRun,
    deps: OutputRuntimeDeps,
) -> tuple[dict[str, Any] | list[Any] | None, list[dict[str, Any]] | None]:
    structured_output: dict[str, Any] | list[Any] | None = None
    artifacts: list[dict[str, Any]] | None = None

    compiled = deps.compile_validators([step])

    if step.output_type == "json":
        structured_output = deps.parse_json_output(full_text)
        validator = compiled.get(("output", step.step_order))
        if validator:
            deps.validate_against_contract(
                structured_output,
                step.output_contract or {},
                label=f"Step {step.step_order} output",
            )
    elif step.output_type in ("pdf", "docx"):
        if step.output_contract:
            pre_render_data = deps.parse_json_output(full_text)
            deps.validate_against_contract(
                pre_render_data,
                step.output_contract,
                label=f"Step {step.step_order} output (pre-render)",
            )
        blob, mimetype, filename = deps.render_document(
            full_text,
            step.output_type,
            step_order=step.step_order,
        )
        file_record = await deps.file_repo.add(
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
        artifacts = [
            {
                "file_id": str(file_record.id),
                "name": filename,
                "mimetype": mimetype,
                "size": len(blob),
            }
        ]

    return structured_output, artifacts
