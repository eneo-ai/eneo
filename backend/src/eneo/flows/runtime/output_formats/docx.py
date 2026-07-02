from __future__ import annotations

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.enums import FlowOutputType
from eneo.flows.runtime.output_formats.base import (
    OutputFormatProcessingContext,
    OutputFormatProcessingResult,
    document_prefers_native_json_object_mode,
    document_prompt_instructions,
    process_structured_document_output,
    render_document_output,
)


class DocxOutputFormatSpec:
    def prompt_instructions(
        self, output_contract: FlowPersistedJsonObject | None
    ) -> tuple[str, ...]:
        return document_prompt_instructions(
            artifact_name="DOCX", output_contract=output_contract
        )

    def should_request_native_json_object_mode(
        self, output_contract: FlowPersistedJsonObject | None
    ) -> bool:
        return document_prefers_native_json_object_mode(output_contract)

    def process_model_output(
        self,
        full_text: str,
        *,
        step_order: int,
        output_contract: FlowPersistedJsonObject | None,
        context: OutputFormatProcessingContext,
    ) -> OutputFormatProcessingResult:
        if output_contract is not None:
            return process_structured_document_output(
                full_text,
                output_type=FlowOutputType.DOCX.value,
                step_order=step_order,
                output_contract=output_contract,
                context=context,
            )
        return render_document_output(
            full_text,
            output_type=FlowOutputType.DOCX.value,
            step_order=step_order,
            context=context,
        )
