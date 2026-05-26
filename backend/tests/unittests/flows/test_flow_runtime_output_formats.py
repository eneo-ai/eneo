from __future__ import annotations

import json

import pytest

from intric.flows.enums import FlowOutputType
from intric.flows.runtime.output_formats import resolve_format_spec
from intric.flows.runtime.output_formats.base import append_output_format_instructions
from intric.main.exceptions import TypedIOValidationException


def _prompt_for(
    *,
    output_type: str,
    output_contract: dict[str, object] | None,
    prompt: str,
) -> str:
    spec = resolve_format_spec(output_type)
    return append_output_format_instructions(
        prompt, spec.prompt_instructions(output_contract)
    )


def test_output_format_registry_is_total_for_flow_output_types() -> None:
    for output_type in FlowOutputType:
        assert resolve_format_spec(output_type.value) is not None


def test_resolve_format_spec_rejects_unknown_output_type() -> None:
    with pytest.raises(TypedIOValidationException) as exc_info:
        resolve_format_spec("presentation")

    assert str(exc_info.value) == "Unsupported flow output type: presentation"
    assert exc_info.value.code == "flow_unsupported_output_type"
    assert exc_info.value.context == {"output_type": "presentation"}


@pytest.mark.parametrize("prompt", ["", "Foo", "Foo\n", "Foo bar"])
def test_empty_output_format_instructions_keep_prompt_byte_identical(
    prompt: str,
) -> None:
    assert append_output_format_instructions(prompt, ()) == prompt


def test_output_format_instructions_match_current_empty_prompt_behavior() -> None:
    assert append_output_format_instructions("", ("x", "y")) == "x\ny"
    assert append_output_format_instructions("   ", ("x", "y")) == "x\ny"
    assert append_output_format_instructions("Prompt", ("x", "y")) == "Prompt\n\nx\ny"


def test_text_output_appends_no_prompt_instructions() -> None:
    assert (
        _prompt_for(
            output_type="text",
            output_contract={"type": "object"},
            prompt="Analyze the text",
        )
        == "Analyze the text"
    )


def test_json_output_prompt_without_schema_matches_current_instructions() -> None:
    prompt = _prompt_for(
        output_type="json",
        output_contract=None,
        prompt="Analyze the text",
    )

    assert prompt == "\n".join(
        [
            "Analyze the text",
            "",
            "Return ONLY valid JSON.",
            "Do not include markdown code fences, commentary, or any surrounding text.",
            "The top-level JSON value must be an object or array.",
        ]
    )


def test_json_output_prompt_with_schema_matches_current_instructions() -> None:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    schema_json = json.dumps(schema, ensure_ascii=False, sort_keys=True)

    prompt = _prompt_for(
        output_type="json",
        output_contract=schema,
        prompt="Analyze the text",
    )

    assert prompt == "\n".join(
        [
            "Analyze the text",
            "",
            "Return ONLY valid JSON.",
            "Do not include markdown code fences, commentary, or any surrounding text.",
            "The top-level JSON value must be an object or array.",
            "Follow this JSON Schema exactly:",
            schema_json,
        ]
    )


@pytest.mark.parametrize(
    ("output_type", "artifact_name"),
    [(FlowOutputType.PDF.value, "PDF"), (FlowOutputType.DOCX.value, "DOCX")],
)
def test_document_output_prompt_without_schema_matches_current_instructions(
    output_type: str, artifact_name: str
) -> None:
    prompt = _prompt_for(
        output_type=output_type,
        output_contract=None,
        prompt="Generate report",
    )

    assert prompt == "\n".join(
        [
            "Generate report",
            "",
            f"The system will render your answer into a {artifact_name} file after you respond.",
            "Return only the document body as Markdown/plain text content.",
            "Do not output binary file contents, base64, XML/ZIP internals, or PDF object syntax.",
            "For PDF output specifically, do not start the response with %PDF-.",
        ]
    )


@pytest.mark.parametrize(
    ("output_type", "artifact_name"),
    [(FlowOutputType.PDF.value, "PDF"), (FlowOutputType.DOCX.value, "DOCX")],
)
def test_document_output_prompt_with_schema_matches_current_instructions(
    output_type: str, artifact_name: str
) -> None:
    schema = {"type": "object", "properties": {"body": {"type": "string"}}}
    schema_json = json.dumps(schema, ensure_ascii=False, sort_keys=True)

    prompt = _prompt_for(
        output_type=output_type,
        output_contract=schema,
        prompt="Return report data",
    )

    assert prompt == "\n".join(
        [
            "Return report data",
            "",
            f"The system will validate your JSON and render it into a {artifact_name} file after you respond.",
            "Return ONLY valid JSON.",
            "Do not include markdown code fences, commentary, or any surrounding text.",
            "The top-level JSON value must be an object or array.",
            "Use plain text for JSON string values; do not include Markdown formatting markers inside strings.",
            "Follow this JSON Schema exactly:",
            schema_json,
        ]
    )


@pytest.mark.parametrize(
    ("schema", "json_expected", "document_expected"),
    [
        (None, True, False),
        ({"type": "object"}, True, True),
        ({"type": "array"}, False, False),
        ({"type": ["object", "null"]}, True, True),
        ({"type": ["object", "array"]}, False, False),
        ({"properties": {"name": {"type": "string"}}}, True, True),
        ({"items": {"type": "string"}}, False, False),
        ({}, False, False),
    ],
)
def test_native_json_object_mode_matches_current_schema_matrix(
    schema: dict[str, object] | None,
    json_expected: bool,
    document_expected: bool,
) -> None:
    assert (
        resolve_format_spec("json").should_request_native_json_object_mode(schema)
        is json_expected
    )
    assert (
        resolve_format_spec("pdf").should_request_native_json_object_mode(schema)
        is document_expected
    )
    assert (
        resolve_format_spec("docx").should_request_native_json_object_mode(schema)
        is document_expected
    )
    assert (
        resolve_format_spec("text").should_request_native_json_object_mode(schema)
        is False
    )
