from __future__ import annotations

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.runtime.output_formats.base import (
    OutputFormatProcessingContext,
    OutputFormatProcessingResult,
)


class TextOutputFormatSpec:
    def prompt_instructions(
        self, output_contract: FlowPersistedJsonObject | None
    ) -> tuple[str, ...]:
        return ()

    def should_request_native_json_object_mode(
        self, output_contract: FlowPersistedJsonObject | None
    ) -> bool:
        return False

    def process_model_output(
        self,
        full_text: str,
        *,
        step_order: int,
        output_contract: FlowPersistedJsonObject | None,
        context: OutputFormatProcessingContext,
    ) -> OutputFormatProcessingResult:
        return OutputFormatProcessingResult()
