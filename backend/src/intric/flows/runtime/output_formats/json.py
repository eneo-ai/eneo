from __future__ import annotations

from intric.flows.domain.flow import JsonObject
from intric.flows.runtime.output_formats.base import (
    json_schema_instructions,
    schema_yields_top_level_object,
)


class JsonOutputFormatSpec:
    def prompt_instructions(
        self, output_contract: JsonObject | None
    ) -> tuple[str, ...]:
        return json_schema_instructions(output_contract)

    def should_request_native_json_object_mode(
        self, output_contract: JsonObject | None
    ) -> bool:
        if output_contract is None:
            return True
        return schema_yields_top_level_object(output_contract)
