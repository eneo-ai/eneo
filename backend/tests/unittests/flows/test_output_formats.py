from __future__ import annotations

import json

import pytest

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.enums import FlowOutputType
from eneo.flows.output_processing import StructuredOutputValue
from eneo.flows.runtime.output_formats.base import (
    EnsureSourceWithinLimitsFn,
    OutputFormatProcessingContext,
    OutputFormatSpec,
    ParseJsonOutputFn,
    RenderDocumentFn,
    RenderStructuredDocumentFn,
    ValidateAgainstContractFn,
)
from eneo.flows.runtime.output_formats.docx import DocxOutputFormatSpec
from eneo.flows.runtime.output_formats.json import JsonOutputFormatSpec
from eneo.flows.runtime.output_formats.pdf import PdfOutputFormatSpec
from eneo.flows.runtime.output_formats.text import TextOutputFormatSpec


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
        title: str,
    ) -> tuple[bytes, str]:
        raise AssertionError(f"render_document was not expected: {output_type}")

    def _render_structured_not_expected(
        data: StructuredOutputValue,
        output_type: str,
        *,
        step_order: int,
        title: str,
        schema: FlowPersistedJsonObject | None = None,
    ) -> tuple[bytes, str]:
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
        document_title="Rapport 2026-09-23",
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


_ALL_STRUCTURED_SPECS = [
    JsonOutputFormatSpec(),
    DocxOutputFormatSpec(),
    PdfOutputFormatSpec(),
]


def _process_structured(
    spec: OutputFormatSpec,
    parsed: StructuredOutputValue,
    contract: FlowPersistedJsonObject,
    raw_text: str = "{}",
):
    def _parse(raw_text: str) -> StructuredOutputValue:
        return parsed

    def _validate(data: object, schema: FlowPersistedJsonObject, *, label: str) -> None:
        pass

    def _render_structured(
        data: StructuredOutputValue,
        rendered_output_type: str,
        *,
        step_order: int,
        title: str,
        schema: FlowPersistedJsonObject | None = None,
    ) -> tuple[bytes, str]:
        return b"rendered", "application/test"

    return spec.process_model_output(
        raw_text,
        step_order=4,
        output_contract=contract,
        context=_context(
            parse_json_output=_parse,
            validate_against_contract=_validate,
            render_structured_document=_render_structured,
            json_contract_validation_enabled=True,
        ),
    )


def _avvikelser_contract(item_keys: list[str]) -> FlowPersistedJsonObject:
    return {
        "type": "object",
        "required": ["avvikelser"],
        "properties": {
            "avvikelser": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": item_keys,
                    "properties": {key: {"type": "string"} for key in item_keys},
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }


@pytest.mark.parametrize("spec", _ALL_STRUCTURED_SPECS)
def test_structured_output_formats_rename_respelled_keys_and_report_them(
    spec: OutputFormatSpec,
) -> None:
    parsed: StructuredOutputValue = {
        "avvikelser": [
            {"vad_vi_avser_att_forelagga_om": "Rätta"},
            {"vad_vi_avser_att_forelägga_om": "Komplettera"},
        ]
    }

    result = _process_structured(
        spec, parsed, _avvikelser_contract(["vad_vi_avser_att_forelagga_om"])
    )

    assert result.structured_output == {
        "avvikelser": [
            {"vad_vi_avser_att_forelagga_om": "Rätta"},
            {"vad_vi_avser_att_forelagga_om": "Komplettera"},
        ]
    }
    assert [
        (diagnostic.code, diagnostic.severity) for diagnostic in result.diagnostics
    ] == [("typed_output_keys_renamed", "warning")]
    assert result.diagnostics[0].message == (
        "Renamed 1 field to the contract spelling: "
        "/avvikelser/1/vad_vi_avser_att_forelägga_om -> "
        "/avvikelser/1/vad_vi_avser_att_forelagga_om"
    )
    # The text the step persists is the conformed value, serialised like the
    # assembled output of the mapped steps.
    assert result.conformed_text == json.dumps(
        result.structured_output, ensure_ascii=False
    )


@pytest.mark.parametrize("spec", _ALL_STRUCTURED_SPECS)
def test_structured_output_formats_keep_the_model_text_when_nothing_is_renamed(
    spec: OutputFormatSpec,
) -> None:
    exact: StructuredOutputValue = {"avvikelser": [{"avvikelse": "Rätta"}]}
    pruned: StructuredOutputValue = {
        "avvikelser": [{"avvikelse": "Rätta", "extra": "dropped"}]
    }
    contract = _avvikelser_contract(["avvikelse"])

    exact_result = _process_structured(spec, exact, contract)
    pruned_result = _process_structured(spec, pruned, contract)

    assert exact_result.conformed_text is None
    assert exact_result.diagnostics == ()
    assert pruned_result.conformed_text is None
    assert [d.code for d in pruned_result.diagnostics] == [
        "typed_output_extra_properties_dropped"
    ]


def test_renamed_keys_message_counts_and_pluralises() -> None:
    parsed: StructuredOutputValue = {
        "avvikelser": [{"vad_vi_avser_att_forelägga_om": f"V{i}"} for i in range(4)]
    }

    result = _process_structured(
        JsonOutputFormatSpec(),
        parsed,
        _avvikelser_contract(["vad_vi_avser_att_forelagga_om"]),
    )

    message = result.diagnostics[0].message
    assert message.startswith("Renamed 4 fields to the contract spelling: ")
    assert message.count(" -> ") == 4


def test_dropped_keys_message_counts_and_pluralises() -> None:
    parsed: StructuredOutputValue = {"avvikelser": [{"avvikelse": "A", "x": 1, "y": 2}]}

    result = _process_structured(
        JsonOutputFormatSpec(), parsed, _avvikelser_contract(["avvikelse"])
    )

    assert result.diagnostics[0].message == (
        "Dropped 2 undeclared fields: /avvikelser/0/x, /avvikelser/0/y"
    )


def test_reported_paths_stop_at_twenty_and_say_how_many_more() -> None:
    parsed: StructuredOutputValue = {
        "avvikelser": [{"avvikelse": "A", "extra": "x"} for _ in range(25)]
    }
    renamed: StructuredOutputValue = {
        "avvikelser": [{"Avvikelse": "A"} for _ in range(25)]
    }
    contract = _avvikelser_contract(["avvikelse"])

    dropped_message = (
        _process_structured(JsonOutputFormatSpec(), parsed, contract)
        .diagnostics[0]
        .message
    )
    renamed_message = (
        _process_structured(JsonOutputFormatSpec(), renamed, contract)
        .diagnostics[0]
        .message
    )

    assert dropped_message.startswith("Dropped 25 undeclared fields: ")
    assert dropped_message.endswith("; 5 more omitted")
    assert dropped_message.count("/extra") == 20
    assert renamed_message.startswith("Renamed 25 fields to the contract spelling: ")
    assert renamed_message.endswith("; 5 more omitted")
    assert renamed_message.count(" -> ") == 20


def test_a_reported_path_is_cut_at_two_hundred_characters() -> None:
    long_key = "z" * 300
    parsed: StructuredOutputValue = {"avvikelser": [{"avvikelse": "A", long_key: 1}]}

    result = _process_structured(
        JsonOutputFormatSpec(), parsed, _avvikelser_contract(["avvikelse"])
    )

    reported = result.diagnostics[0].message.split(": ", 1)[1]
    assert len(reported) == 200
    assert reported.startswith("/avvikelser/0/zzz")
    assert reported.endswith("...")


def test_the_whole_reported_message_is_cut_at_sixteen_hundred_characters() -> None:
    keys = [f"{index:02d}" + "k" * 150 for index in range(20)]
    parsed: StructuredOutputValue = {
        "avvikelser": [{"avvikelse": "A", **{k: 1 for k in keys}}]
    }

    result = _process_structured(
        JsonOutputFormatSpec(), parsed, _avvikelser_contract(["avvikelse"])
    )

    assert len(result.diagnostics[0].message) == 1600


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
        tuple[StructuredOutputValue, str, int, str, FlowPersistedJsonObject | None]
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
        title: str,
        schema: FlowPersistedJsonObject | None = None,
    ) -> tuple[bytes, str]:
        render_calls.append((data, rendered_output_type, step_order, title, schema))
        return b"rendered", "application/test"

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
        (result.structured_output, output_type, 5, "Rapport 2026-09-23", contract),
    ]
    assert result.artifact is not None
    assert result.artifact.blob == b"rendered"
