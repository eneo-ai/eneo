from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from intric.files.file_models import FileType
from intric.main.exceptions import TypedIOValidationException
from intric.flows.runtime.output_runtime import OutputRuntimeDeps, process_typed_output


@dataclass
class _Step:
    step_order: int
    output_type: str
    output_contract: dict | None = None


@dataclass
class _Run:
    tenant_id: UUID


@pytest.mark.asyncio
async def test_process_typed_output_json_with_contract_validation() -> None:
    step = _Step(step_order=1, output_type="json", output_contract={"type": "object"})
    run = _Run(tenant_id=uuid4())

    deps = OutputRuntimeDeps(
        file_repo=SimpleNamespace(add=AsyncMock()),
        user_id=uuid4(),
        compile_validators=lambda steps: {("output", 1): object()},
        parse_json_output=lambda text: {"ok": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (b"", "", ""),
    )

    structured, artifacts = await process_typed_output(
        full_text='{"ok": true}',
        step=step,
        run=run,
        deps=deps,
    )

    assert structured == {"ok": True}
    assert artifacts is None


@pytest.mark.asyncio
async def test_process_typed_output_json_without_compiled_validator_skips_contract_validation() -> None:
    step = _Step(step_order=2, output_type="json", output_contract={"type": "object"})
    run = _Run(tenant_id=uuid4())

    def _unexpected_validate(*args, **kwargs) -> None:
        raise AssertionError("validate_against_contract should not run without compiled validator")

    deps = OutputRuntimeDeps(
        file_repo=SimpleNamespace(add=AsyncMock()),
        user_id=uuid4(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"ok": True},
        validate_against_contract=_unexpected_validate,
        render_document=lambda text, output_type, step_order: (b"", "", ""),
    )

    structured, artifacts = await process_typed_output(
        full_text='{"ok": true}',
        step=step,
        run=run,
        deps=deps,
    )

    assert structured == {"ok": True}
    assert artifacts is None


@pytest.mark.asyncio
async def test_process_typed_output_docx_creates_artifact_file() -> None:
    step = _Step(step_order=3, output_type="docx", output_contract=None)
    run = _Run(tenant_id=uuid4())
    file_id = uuid4()
    file_repo = SimpleNamespace(add=AsyncMock(return_value=SimpleNamespace(id=file_id)))
    blob = b"docx-bytes"
    mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    filename = "step-3-output.docx"
    user_id = uuid4()

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        user_id=user_id,
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"unused": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (blob, mimetype, filename),
    )

    structured, artifacts = await process_typed_output(
        full_text="Rendered docx content",
        step=step,
        run=run,
        deps=deps,
    )

    assert structured is None
    assert artifacts == [
        {
            "file_id": str(file_id),
            "name": filename,
            "mimetype": mimetype,
            "size": len(blob),
        }
    ]
    file_repo.add.assert_awaited_once()
    file_create = file_repo.add.await_args.args[0]
    assert file_create.file_type == FileType.DOCUMENT
    assert file_create.blob == blob
    assert file_create.user_id == user_id
    assert file_create.tenant_id == run.tenant_id


@pytest.mark.asyncio
async def test_process_typed_output_docx_validates_pre_render_contract() -> None:
    step = _Step(step_order=4, output_type="docx", output_contract={"type": "object"})
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    validate_calls: list[tuple[object, dict, str]] = []

    def _validate(data, schema, label):
        validate_calls.append((data, schema, label))

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        user_id=uuid4(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"structured": 1},
        validate_against_contract=_validate,
        render_document=lambda text, output_type, step_order: (b"pdf", "application/pdf", "x.pdf"),
    )

    await process_typed_output(
        full_text='{"structured": 1}',
        step=step,
        run=run,
        deps=deps,
    )

    assert validate_calls == [
        (
            {"structured": 1},
            {"type": "object"},
            "Step 4 output (pre-render)",
        )
    ]


@pytest.mark.asyncio
async def test_process_typed_output_docx_without_contract_does_not_parse_json() -> None:
    step = _Step(step_order=5, output_type="docx", output_contract=None)
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock(return_value=SimpleNamespace(id=uuid4())))

    def _parse_not_expected(_: str) -> dict[str, bool]:
        raise AssertionError("parse_json_output should not run without output_contract")

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        user_id=uuid4(),
        compile_validators=lambda steps: {},
        parse_json_output=_parse_not_expected,
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (b"docx", "application/docx", "x.docx"),
    )

    structured, artifacts = await process_typed_output(
        full_text="pre-render text",
        step=step,
        run=run,
        deps=deps,
    )

    assert structured is None
    assert artifacts is not None
    file_repo.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_typed_output_unknown_type_returns_empty() -> None:
    step = _Step(step_order=6, output_type="text", output_contract=None)
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock())

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        user_id=uuid4(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"ok": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (b"", "", ""),
    )

    structured, artifacts = await process_typed_output(
        full_text="plain text output",
        step=step,
        run=run,
        deps=deps,
    )

    assert structured is None
    assert artifacts is None
    file_repo.add.assert_not_called()


@pytest.mark.asyncio
async def test_process_typed_output_json_contract_violation_propagates() -> None:
    step = _Step(step_order=7, output_type="json", output_contract={"type": "object"})
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock())

    def _raise_contract(*args, **kwargs):
        raise TypedIOValidationException("bad schema", code="typed_io_contract_violation")

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        user_id=uuid4(),
        compile_validators=lambda steps: {("output", 7): object()},
        parse_json_output=lambda text: {"ok": True},
        validate_against_contract=_raise_contract,
        render_document=lambda text, output_type, step_order: (b"", "", ""),
    )

    with pytest.raises(TypedIOValidationException) as exc:
        await process_typed_output(
            full_text='{"ok": true}',
            step=step,
            run=run,
            deps=deps,
        )

    assert exc.value.code == "typed_io_contract_violation"


@pytest.mark.asyncio
async def test_process_typed_output_render_failure_propagates() -> None:
    step = _Step(step_order=8, output_type="docx", output_contract=None)
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock())

    def _fail_render(*args, **kwargs):
        raise RuntimeError("renderer unavailable")

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        user_id=uuid4(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"unused": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=_fail_render,
    )

    with pytest.raises(RuntimeError, match="renderer unavailable"):
        await process_typed_output(
            full_text="some output",
            step=step,
            run=run,
            deps=deps,
        )

    file_repo.add.assert_not_called()


@pytest.mark.asyncio
async def test_process_typed_output_file_repo_failure_propagates() -> None:
    step = _Step(step_order=9, output_type="pdf", output_contract=None)
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock(side_effect=RuntimeError("db down")))

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        user_id=uuid4(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"unused": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (b"pdf", "application/pdf", "x.pdf"),
    )

    with pytest.raises(RuntimeError, match="db down"):
        await process_typed_output(
            full_text="some output",
            step=step,
            run=run,
            deps=deps,
        )
