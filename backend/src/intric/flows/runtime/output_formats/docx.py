from __future__ import annotations

from intric.flows.domain.flow import JsonObject
from intric.flows.runtime.output_formats.base import (
    document_prefers_native_json_object_mode,
    document_prompt_instructions,
)


class DocxOutputFormatSpec:
    def prompt_instructions(
        self, output_contract: JsonObject | None
    ) -> tuple[str, ...]:
        return document_prompt_instructions(
            artifact_name="DOCX", output_contract=output_contract
        )

    def should_request_native_json_object_mode(
        self, output_contract: JsonObject | None
    ) -> bool:
        return document_prefers_native_json_object_mode(output_contract)
