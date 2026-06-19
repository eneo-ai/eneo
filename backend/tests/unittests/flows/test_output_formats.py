from __future__ import annotations

import pytest

from intric.flows.domain.flow import FlowPersistedJsonObject
from intric.flows.enums import FlowOutputType
from intric.flows.output_processing import StructuredOutputValue
from intric.flows.runtime.output_formats.base import (
    EnsureSourceWithinLimitsFn,
    OutputFormatProcessingContext,
    OutputFormatSpec,
    ParseJsonOutputFn,
    RenderDocumentFn,
    RenderStructuredDocumentFn,
    ValidateAgainstContractFn,
)
from intric.flows.runtime.output_formats.docx import DocxOutputFormatSpec
from intric.flows.runtime.output_formats.json import JsonOutputFormatSpec
from intric.flows.runtime.output_formats.pdf import PdfOutputFormatSpec
from intric.flows.runtime.output_formats.text import TextOutputFormatSpec


def _context(
    *,
    parse_json_output: ParseJsonOutputFn | None = None,
    validate_against_contract: ValidateAgainstContractFn | None = None,
    render_document: RenderDocumentFn | None = None,
    render_structured_document: RenderStructuredDocumentFn | None = None,
    ensure_source_within_limits: EnsureSourceWithinLimitsFn | None = None,
    json_contract_validation_enabled: bool = False,
) -> OutputFormatProcessingContext:
    def _parse_not_expected(raw_text: str) -> StructuredOutputValue:
        raise AssertionError(f"parse_json_output was not expected: {raw_text}")

    def _validate_not_expected(
        data: object,
        schema: FlowPersistedJsonObject,
        *,
        label: str,
    ) -> None:
        raise AssertionError(f"validate_against_contract was not expected: {label}")

    def _render_document_not_expected(
        text: str,
        output_type: str,
        *,
        step_order: int,
    ) -> tuple[bytes, str, str]:
        raise AssertionError(f"render_document was not expected: {output_type}")

    def _render_structured_not_expected(
        data: StructuredOutputValue,
        output_type: str,
        *,
        step_order: int,
        schema: FlowPersistedJsonObject | None = None,
    ) -> tuple[bytes, str, str]:
        raise AssertionError(
            f"render_structured_document was not expected: {output_type}"
        )

    def _ensure_limits_not_expected(text: str) -> None:
        raise AssertionError(f"ensure_source_within_limits was not expected: {text}")

    return OutputFormatProcessingContext(
        parse_json_output=parse_json_output or _parse_not_expected,
        validate_against_contract=(validate_against_contract or _validate_not_expected),
        render_document=render_document or _render_document_not_expected,
        render_structured_document=(
            render_structured_document or _render_structured_not_expected
        ),
        ensure_source_within_limits=(
            ensure_source_within_limits or _ensure_limits_not_expected
        ),
        json_contract_validation_enabled=json_contract_validation_enabled,
    )


def test_text_output_format_processing_is_noop() -> None:
    result = TextOutputFormatSpec().process_model_output(
        "plain response",
        step_order=1,
        output_contract=None,
        context=_context(),
    )

    assert result.structured_output is None
    assert result.artifact is None
    assert result.diagnostics == ()


def test_json_output_format_skips_contract_validation_without_compiled_validator() -> (
    None
):
    parsed: StructuredOutputValue = {"ok": True, "extra": "kept"}
    validate_calls: list[str] = []

    def _parse(raw_text: str) -> StructuredOutputValue:
        return parsed

    def _validate(data: object, schema: FlowPersistedJsonObject, *, label: str) -> None:
        validate_calls.append(label)

    result = JsonOutputFormatSpec().process_model_output(
        '{"ok": true, "extra": "kept"}',
        step_order=2,
        output_contract={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "additionalProperties": False,
        },
        context=_context(
            parse_json_output=_parse,
            validate_against_contract=_validate,
            json_contract_validation_enabled=False,
        ),
    )

    assert result.structured_output == {"ok": True, "extra": "kept"}
    assert result.diagnostics == ()
    assert validate_calls == []


def test_json_output_format_prunes_and_validates_when_compiled_validator_exists() -> (
    None
):
    parsed: StructuredOutputValue = {"ok": True, "extra": "dropped"}
    validate_payloads: list[object] = []

    def _parse(raw_text: str) -> StructuredOutputValue:
        return parsed

    def _validate(data: object, schema: FlowPersistedJsonObject, *, label: str) -> None:
        validate_payloads.append(data)

    result = JsonOutputFormatSpec().process_model_output(
        '{"ok": true, "extra": "dropped"}',
        step_order=3,
        output_contract={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "additionalProperties": False,
        },
        context=_context(
            parse_json_output=_parse,
            validate_against_contract=_validate,
            json_contract_validation_enabled=True,
        ),
    )

    assert result.structured_output == {"ok": True}
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "typed_output_extra_properties_dropped"
    ]
    assert validate_payloads == [result.structured_output]


def test_pdf_output_format_preserves_raw_pdf_bytes() -> None:
    limit_calls: list[str] = []

    def _ensure_limits(text: str) -> None:
        limit_calls.append(text)

    raw_pdf = "%PDF-1.4\n%%EOF"
    result = PdfOutputFormatSpec().process_model_output(
        f"\n{raw_pdf}",
        step_order=4,
        output_contract=None,
        context=_context(ensure_source_within_limits=_ensure_limits),
    )

    assert result.artifact is not None
    assert result.artifact.blob == raw_pdf.encode("latin-1")
    assert result.artifact.mimetype == "application/pdf"
    assert result.artifact.filename == "step_4_output.pdf"
    assert limit_calls == [f"\n{raw_pdf}"]


@pytest.mark.parametrize(
    ("spec", "output_type"),
    [
        (DocxOutputFormatSpec(), FlowOutputType.DOCX.value),
        (PdfOutputFormatSpec(), FlowOutputType.PDF.value),
    ],
)
def test_document_output_formats_share_structured_contract_pipeline(
    spec: OutputFormatSpec,
    output_type: str,
) -> None:
    parsed: StructuredOutputValue = {"title": "Report", "extra": "dropped"}
    validate_payloads: list[object] = []
    render_calls: list[
        tuple[StructuredOutputValue, str, int, FlowPersistedJsonObject | None]
    ] = []
    contract: FlowPersistedJsonObject = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "additionalProperties": False,
    }

    def _parse(raw_text: str) -> StructuredOutputValue:
        return parsed

    def _validate(data: object, schema: FlowPersistedJsonObject, *, label: str) -> None:
        validate_payloads.append(data)

    def _render_structured(
        data: StructuredOutputValue,
        rendered_output_type: str,
        *,
        step_order: int,
        schema: FlowPersistedJsonObject | None = None,
    ) -> tuple[bytes, str, str]:
        render_calls.append((data, rendered_output_type, step_order, schema))
        return b"rendered", "application/test", f"step-{step_order}"

    result = spec.process_model_output(
        '{"title": "Report", "extra": "dropped"}',
        step_order=5,
        output_contract=contract,
        context=_context(
            parse_json_output=_parse,
            validate_against_contract=_validate,
            render_structured_document=_render_structured,
        ),
    )

    assert result.structured_output == {"title": "Report"}
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "typed_output_extra_properties_dropped"
    ]
    assert validate_payloads == [result.structured_output]
    assert render_calls == [
        (result.structured_output, output_type, 5, contract),
    ]
    assert result.artifact is not None
    assert result.artifact.blob == b"rendered"
