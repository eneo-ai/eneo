from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Protocol, cast

from intric.flows.domain.flow import JsonObject


class OutputFormatSpec(Protocol):
    def prompt_instructions(
        self, output_contract: JsonObject | None
    ) -> tuple[str, ...]: ...

    def should_request_native_json_object_mode(
        self, output_contract: JsonObject | None
    ) -> bool: ...


def append_output_format_instructions(prompt: str, instructions: Sequence[str]) -> str:
    if not instructions:
        return prompt
    suffix = "\n".join(instructions)
    return f"{prompt}\n\n{suffix}" if prompt.strip() else suffix


def schema_yields_top_level_object(schema: JsonObject) -> bool:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type == "object"
    if isinstance(raw_type, list):
        declared = {
            item for item in cast(list[object], raw_type) if isinstance(item, str)
        }
        return "object" in declared and "array" not in declared
    if isinstance(schema.get("properties"), dict):
        return True
    if "items" in schema:
        return False
    return False


def json_schema_instructions(output_contract: JsonObject | None) -> tuple[str, ...]:
    instructions = (
        "Return ONLY valid JSON.",
        "Do not include markdown code fences, commentary, or any surrounding text.",
        "The top-level JSON value must be an object or array.",
    )
    if output_contract is None:
        return instructions
    schema_json = json.dumps(output_contract, ensure_ascii=False, sort_keys=True)
    return (
        *instructions,
        "Follow this JSON Schema exactly:",
        schema_json,
    )


def document_prompt_instructions(
    *, artifact_name: str, output_contract: JsonObject | None
) -> tuple[str, ...]:
    if output_contract is None:
        return (
            f"The system will render your answer into a {artifact_name} file after you respond.",
            "Return only the document body as Markdown/plain text content.",
            "Do not output binary file contents, base64, XML/ZIP internals, or PDF object syntax.",
            "For PDF output specifically, do not start the response with %PDF-.",
        )
    schema_json = json.dumps(output_contract, ensure_ascii=False, sort_keys=True)
    return (
        f"The system will validate your JSON and render it into a {artifact_name} file after you respond.",
        "Return ONLY valid JSON.",
        "Do not include markdown code fences, commentary, or any surrounding text.",
        "The top-level JSON value must be an object or array.",
        "Use plain text for JSON string values; do not include Markdown formatting markers inside strings.",
        "Follow this JSON Schema exactly:",
        schema_json,
    )


def document_prefers_native_json_object_mode(
    output_contract: JsonObject | None,
) -> bool:
    if output_contract is None:
        return False
    return schema_yields_top_level_object(output_contract)
