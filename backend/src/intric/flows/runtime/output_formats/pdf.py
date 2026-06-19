from __future__ import annotations

from intric.flows.domain.flow import FlowPersistedJsonObject
from intric.flows.enums import FlowOutputType
from intric.flows.runtime.output_formats.base import (
    OutputFormatProcessingContext,
    OutputFormatProcessingResult,
    RenderedOutputArtifact,
    document_prefers_native_json_object_mode,
    document_prompt_instructions,
    process_structured_document_output,
    render_document_output,
)


class PdfOutputFormatSpec:
    def prompt_instructions(
        self, output_contract: FlowPersistedJsonObject | None
    ) -> tuple[str, ...]:
        return document_prompt_instructions(
            artifact_name="PDF", output_contract=output_contract
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
                output_type=FlowOutputType.PDF.value,
                step_order=step_order,
                output_contract=output_contract,
                context=context,
            )
        if _is_pdf_bytes_text(full_text):
            context.ensure_source_within_limits(full_text)
            return OutputFormatProcessingResult(
                artifact=RenderedOutputArtifact(
                    blob=_pdf_bytes_from_text(full_text),
                    mimetype="application/pdf",
                    filename=f"step_{step_order}_output.pdf",
                )
            )
        return render_document_output(
            full_text,
            output_type=FlowOutputType.PDF.value,
            step_order=step_order,
            context=context,
        )


def _is_pdf_bytes_text(text: str) -> bool:
    return text.lstrip().startswith("%PDF-")


def _pdf_bytes_from_text(text: str) -> bytes:
    return text.lstrip().encode("latin-1", errors="replace")
