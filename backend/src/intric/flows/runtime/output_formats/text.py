from __future__ import annotations

from intric.flows.domain.flow import JsonObject


class TextOutputFormatSpec:
    def prompt_instructions(
        self, output_contract: JsonObject | None
    ) -> tuple[str, ...]:
        return ()

    def should_request_native_json_object_mode(
        self, output_contract: JsonObject | None
    ) -> bool:
        return False
