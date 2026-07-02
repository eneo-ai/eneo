from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from eneo.flows.enums import FlowOutputType
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.output_formats.base import OutputFormatSpec
from eneo.flows.runtime.output_formats.docx import DocxOutputFormatSpec
from eneo.flows.runtime.output_formats.json import JsonOutputFormatSpec
from eneo.flows.runtime.output_formats.pdf import PdfOutputFormatSpec
from eneo.flows.runtime.output_formats.text import TextOutputFormatSpec
from eneo.main.exceptions import TypedIOValidationException

TEXT_OUTPUT_FORMAT = TextOutputFormatSpec()
JSON_OUTPUT_FORMAT = JsonOutputFormatSpec()
PDF_OUTPUT_FORMAT = PdfOutputFormatSpec()
DOCX_OUTPUT_FORMAT = DocxOutputFormatSpec()

OUTPUT_FORMAT_SPECS: Mapping[FlowOutputType, OutputFormatSpec] = MappingProxyType(
    {
        FlowOutputType.TEXT: TEXT_OUTPUT_FORMAT,
        FlowOutputType.JSON: JSON_OUTPUT_FORMAT,
        FlowOutputType.PDF: PDF_OUTPUT_FORMAT,
        FlowOutputType.DOCX: DOCX_OUTPUT_FORMAT,
    }
)


def resolve_format_spec(raw_output_type: str) -> OutputFormatSpec:
    try:
        output_type = FlowOutputType(raw_output_type)
    except ValueError as exc:
        raise TypedIOValidationException(
            f"Unsupported flow output type: {raw_output_type}",
            code=FlowApiErrorCode.UNSUPPORTED_OUTPUT_TYPE.value,
            context={"output_type": raw_output_type},
        ) from exc
    return OUTPUT_FORMAT_SPECS[output_type]


__all__ = [
    "DOCX_OUTPUT_FORMAT",
    "JSON_OUTPUT_FORMAT",
    "OUTPUT_FORMAT_SPECS",
    "PDF_OUTPUT_FORMAT",
    "TEXT_OUTPUT_FORMAT",
    "OutputFormatSpec",
    "resolve_format_spec",
]
