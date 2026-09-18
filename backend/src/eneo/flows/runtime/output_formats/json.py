from __future__ import annotations

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.runtime.output_formats.base import (
    OutputFormatProcessingContext,
    OutputFormatProcessingResult,
    json_schema_instructions,
    prune_model_output_extras,
)


class JsonOutputFormatSpec:
    def prompt_instructions(
        self, output_contract: FlowPersistedJsonObject | None
    ) -> tuple[str, ...]:
        return json_schema_instructions(output_contract)

    def requests_structured_output(
        self, output_contract: FlowPersistedJsonObject | None
    ) -> bool:
        return True

    def process_model_output(
        self,
        full_text: str,
        *,
        step_order: int,
        output_contract: FlowPersistedJsonObject | None,
        context: OutputFormatProcessingContext,
    ) -> OutputFormatProcessingResult:
        structured_output = context.parse_json_output(full_text)
        diagnostics = ()
        if output_contract is not None and context.json_contract_validation_enabled:
            diagnostics = prune_model_output_extras(structured_output, output_contract)
            context.validate_against_contract(
                structured_output,
                output_contract,
                label=f"Step {step_order} output",
            )
        return OutputFormatProcessingResult(
            structured_output=structured_output,
            diagnostics=diagnostics,
        )
