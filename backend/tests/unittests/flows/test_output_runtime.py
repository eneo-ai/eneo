from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from intric.authentication.principal_types import PrincipalType
from intric.files.file_models import FileType
from intric.flows.principal import FlowPrincipal
from intric.flows.runtime.document_rendering.limits import DocumentRenderLimits
from intric.flows.runtime.output_runtime import (
    OutputRuntimeDeps,
    TypedOutputProcessingResult,
    process_typed_output,
)
from intric.main.exceptions import TypedIOValidationException


@dataclass
class _Step:
    step_order: int
    output_type: str
    output_contract: dict | None = None


@dataclass
class _Run:
    tenant_id: UUID


def _user_principal(user_id: UUID | None = None) -> FlowPrincipal:
    return FlowPrincipal(
        principal_type=PrincipalType.USER,
        principal_user_id=user_id or uuid4(),
    )


@pytest.mark.asyncio
async def test_process_typed_output_json_with_contract_validation() -> None:
    step = _Step(step_order=1, output_type="json", output_contract={"type": "object"})
    run = _Run(tenant_id=uuid4())

    deps = OutputRuntimeDeps(
        file_repo=SimpleNamespace(add=AsyncMock()),
        principal=_user_principal(),
        compile_validators=lambda steps: {("output", 1): object()},
        parse_json_output=lambda text: {"ok": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (b"", "", ""),
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
    )

    result = await process_typed_output(
        full_text='{"ok": true}',
        step=step,
        run=run,
        deps=deps,
    )

    assert result.structured_output == {"ok": True}
    assert result.artifacts is None


@pytest.mark.asyncio
async def test_process_typed_output_json_without_compiled_validator_skips_contract_validation() -> (
    None
):
    step = _Step(step_order=2, output_type="json", output_contract={"type": "object"})
    run = _Run(tenant_id=uuid4())

    def _unexpected_validate(*args, **kwargs) -> None:
        raise AssertionError(
            "validate_against_contract should not run without compiled validator"
        )

    deps = OutputRuntimeDeps(
        file_repo=SimpleNamespace(add=AsyncMock()),
        principal=_user_principal(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"ok": True},
        validate_against_contract=_unexpected_validate,
        render_document=lambda text, output_type, step_order: (b"", "", ""),
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
    )

    result = await process_typed_output(
        full_text='{"ok": true}',
        step=step,
        run=run,
        deps=deps,
    )

    assert result.structured_output == {"ok": True}
    assert result.artifacts is None


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
    principal = _user_principal(user_id)

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        principal=principal,
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"unused": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (
            blob,
            mimetype,
            filename,
        ),
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            blob,
            mimetype,
            filename,
        ),
    )

    result = await process_typed_output(
        full_text="Rendered docx content",
        step=step,
        run=run,
        deps=deps,
    )

    assert result.structured_output is None
    assert result.artifacts == [
        {
            "file_id": str(file_id),
            "name": filename,
            "mimetype": mimetype,
            "size": len(blob),
            "checksum": hashlib.sha256(blob).hexdigest(),
            "file_type": "document",
        }
    ]
    file_repo.add.assert_awaited_once()
    file_create = file_repo.add.await_args.args[0]
    assert file_create.file_type == FileType.DOCUMENT
    assert file_create.blob == blob
    assert file_create.owner_type == PrincipalType.USER
    assert file_create.owner_user_id == user_id
    assert file_create.owner_api_key_id is None
    assert file_create.tenant_id == run.tenant_id


@pytest.mark.asyncio
async def test_process_typed_output_pdf_preserves_pdf_bytes_from_model() -> None:
    step = _Step(step_order=8, output_type="pdf", output_contract=None)
    run = _Run(tenant_id=uuid4())
    file_id = uuid4()
    file_repo = SimpleNamespace(add=AsyncMock(return_value=SimpleNamespace(id=file_id)))
    raw_pdf = "%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"

    def _render_not_expected(*args, **kwargs):
        raise AssertionError("raw PDF bytes should be persisted directly")

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        principal=_user_principal(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"unused": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=_render_not_expected,
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
    )

    result = await process_typed_output(
        full_text=f"\n{raw_pdf}",
        step=step,
        run=run,
        deps=deps,
    )

    assert result.structured_output is None
    assert result.artifacts is not None
    assert result.artifacts[0]["mimetype"] == "application/pdf"
    assert result.artifacts[0]["name"] == "step_8_output.pdf"
    file_create = file_repo.add.await_args.args[0]
    assert file_create.blob == raw_pdf.encode("latin-1")


@pytest.mark.asyncio
async def test_process_typed_output_pdf_bytes_obeys_document_render_limits() -> None:
    step = _Step(step_order=8, output_type="pdf", output_contract=None)
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock())

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        principal=_user_principal(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"unused": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (
            b"",
            "",
            "",
        ),
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
        document_render_limits=DocumentRenderLimits(max_source_chars=5),
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await process_typed_output(
            full_text="%PDF-1.4 oversized",
            step=step,
            run=run,
            deps=deps,
        )

    assert exc_info.value.context == {
        "metric": "source_chars",
        "actual": 18,
        "limit": 5,
    }
    file_repo.add.assert_not_called()


@pytest.mark.asyncio
async def test_process_typed_output_docx_renders_validated_structured_contract() -> (
    None
):
    step = _Step(step_order=4, output_type="docx", output_contract={"type": "object"})
    run = _Run(tenant_id=uuid4())
    file_id = uuid4()
    file_repo = SimpleNamespace(add=AsyncMock(return_value=SimpleNamespace(id=file_id)))
    validate_calls: list[tuple[object, dict, str]] = []
    render_calls: list[tuple[object, str, int, dict | None]] = []

    def _validate(data, schema, label):
        validate_calls.append((data, schema, label))

    def _render_structured(data, output_type, step_order, schema=None):
        render_calls.append((data, output_type, step_order, schema))
        return b"docx", "application/docx", "x.docx"

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        principal=_user_principal(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"structured": 1},
        validate_against_contract=_validate,
        render_document=lambda text, output_type, step_order: (
            b"pdf",
            "application/pdf",
            "x.pdf",
        ),
        render_structured_document=_render_structured,
    )

    result = await process_typed_output(
        full_text='{"structured": 1}',
        step=step,
        run=run,
        deps=deps,
    )

    assert result.structured_output == {"structured": 1}
    assert validate_calls == [({"structured": 1}, {"type": "object"}, "Step 4 output")]
    assert render_calls == [({"structured": 1}, "docx", 4, {"type": "object"})]
    assert result.artifacts is not None
    assert result.artifacts[0]["file_id"] == str(file_id)


@pytest.mark.asyncio
async def test_process_typed_output_prunes_extra_item_properties_before_validation() -> (
    None
):
    contract = {
        "type": "object",
        "required": ["beslutslista"],
        "properties": {
            "beslutslista": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["rubrik", "beslut", "omrostning"],
                    "properties": {
                        "rubrik": {"type": "string"},
                        "beslut": {"type": "string"},
                        "omrostning": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }
    parsed = {
        "beslutslista": [
            {
                "rubrik": "Budget",
                "beslut": "Godkänd",
                "omrostning": False,
                "rubrik_kommentar": "extra",
            }
        ]
    }
    validate_calls: list[tuple[object, dict, str]] = []

    def _validate(data, schema, label):
        validate_calls.append((data, schema, label))

    deps = OutputRuntimeDeps(
        file_repo=SimpleNamespace(add=AsyncMock()),
        principal=_user_principal(),
        compile_validators=lambda steps: {("output", 4): object()},
        parse_json_output=lambda text: parsed,
        validate_against_contract=_validate,
        render_document=lambda text, output_type, step_order: (b"", "", ""),
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
    )

    result = await process_typed_output(
        full_text='{"beslutslista":[]}',
        step=_Step(step_order=4, output_type="json", output_contract=contract),
        run=_Run(tenant_id=uuid4()),
        deps=deps,
    )

    assert isinstance(result, TypedOutputProcessingResult)
    assert result.structured_output == {
        "beslutslista": [{"rubrik": "Budget", "beslut": "Godkänd", "omrostning": False}]
    }
    assert result.artifacts is None
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "typed_output_extra_properties_dropped"
    ]
    assert "/beslutslista/0/rubrik_kommentar" in result.diagnostics[0].message
    assert validate_calls == [
        (result.structured_output, contract, "Step 4 output"),
    ]


@pytest.mark.asyncio
async def test_process_typed_output_docx_treats_empty_contract_as_structured() -> None:
    step = _Step(step_order=4, output_type="docx", output_contract={})
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    render_calls: list[tuple[object, str, int, dict | None]] = []

    def _render_structured(data, output_type, step_order, schema=None):
        render_calls.append((data, output_type, step_order, schema))
        return b"docx", "application/docx", "x.docx"

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        principal=_user_principal(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: ["legacy", "data"],
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (
            b"raw-json-doc",
            "application/docx",
            "raw.docx",
        ),
        render_structured_document=_render_structured,
    )

    result = await process_typed_output(
        full_text='["legacy", "data"]',
        step=step,
        run=run,
        deps=deps,
    )

    assert result.structured_output == ["legacy", "data"]
    assert render_calls == [(["legacy", "data"], "docx", 4, {})]
    assert result.artifacts is not None


@pytest.mark.asyncio
async def test_process_typed_output_docx_without_contract_does_not_parse_json() -> None:
    step = _Step(step_order=5, output_type="docx", output_contract=None)
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock(return_value=SimpleNamespace(id=uuid4())))

    def _parse_not_expected(_: str) -> dict[str, bool]:
        raise AssertionError("parse_json_output should not run without output_contract")

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        principal=_user_principal(),
        compile_validators=lambda steps: {},
        parse_json_output=_parse_not_expected,
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (
            b"docx",
            "application/docx",
            "x.docx",
        ),
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
    )

    result = await process_typed_output(
        full_text="pre-render text",
        step=step,
        run=run,
        deps=deps,
    )

    assert result.structured_output is None
    assert result.artifacts is not None
    file_repo.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_typed_output_unknown_type_returns_empty() -> None:
    step = _Step(step_order=6, output_type="text", output_contract=None)
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock())

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        principal=_user_principal(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"ok": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (b"", "", ""),
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
    )

    result = await process_typed_output(
        full_text="plain text output",
        step=step,
        run=run,
        deps=deps,
    )

    assert result.structured_output is None
    assert result.artifacts is None
    file_repo.add.assert_not_called()


@pytest.mark.asyncio
async def test_process_typed_output_json_contract_violation_propagates() -> None:
    step = _Step(step_order=7, output_type="json", output_contract={"type": "object"})
    run = _Run(tenant_id=uuid4())
    file_repo = SimpleNamespace(add=AsyncMock())

    def _raise_contract(*args, **kwargs):
        raise TypedIOValidationException(
            "bad schema", code="typed_io_contract_violation"
        )

    deps = OutputRuntimeDeps(
        file_repo=file_repo,
        principal=_user_principal(),
        compile_validators=lambda steps: {("output", 7): object()},
        parse_json_output=lambda text: {"ok": True},
        validate_against_contract=_raise_contract,
        render_document=lambda text, output_type, step_order: (b"", "", ""),
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
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
        principal=_user_principal(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"unused": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=_fail_render,
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
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
        principal=_user_principal(),
        compile_validators=lambda steps: {},
        parse_json_output=lambda text: {"unused": True},
        validate_against_contract=lambda data, schema, label: None,
        render_document=lambda text, output_type, step_order: (
            b"pdf",
            "application/pdf",
            "x.pdf",
        ),
        render_structured_document=lambda data, output_type, step_order, schema=None: (
            b"",
            "",
            "",
        ),
    )

    with pytest.raises(RuntimeError, match="db down"):
        await process_typed_output(
            full_text="some output",
            step=step,
            run=run,
            deps=deps,
        )
