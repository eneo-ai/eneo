"""Refuse document-dependent definitions before allocating runs or versions."""

from collections.abc import Iterable
from typing import Protocol

from eneo.document_templates.runtime_client import (
    RuntimeUnavailable,
    configured,
    ensure_document_runtime,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import BadRequestException


class DocumentStep(Protocol):
    @property
    def output_type(self) -> str: ...
    @property
    def output_mode(self) -> str: ...


async def require_document_runtime(steps: Iterable[DocumentStep]) -> None:
    if not any(
        step.output_type in {"docx", "pdf"} or step.output_mode == "template_fill"
        for step in steps
    ):
        return
    try:
        if not configured():
            raise RuntimeUnavailable()
        await ensure_document_runtime()
    except RuntimeUnavailable as exc:
        raise BadRequestException(
            "Configure an available shared document runtime before publishing or running document steps.",
            code=FlowApiErrorCode.DOCUMENT_RUNTIME_REQUIRED.value,
        ) from exc
