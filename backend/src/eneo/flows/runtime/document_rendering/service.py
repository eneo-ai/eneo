from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from typing import Any, NoReturn, cast

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.document_rendering.blocks import DocumentBlock
from eneo.flows.runtime.document_rendering.docx_renderer import DocxDocumentRenderer
from eneo.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
    ensure_blocks_within_limits,
    ensure_source_within_limits,
    ensure_structured_value_within_limits,
)
from eneo.flows.runtime.document_rendering.markdown_blocks import (
    parse_markdown_blocks,
)
from eneo.flows.runtime.document_rendering.renderers import DocumentRenderer
from eneo.flows.runtime.document_rendering.structured_blocks import (
    structured_data_to_blocks,
)
from eneo.flows.runtime.document_rendering.weasyprint_renderer import (
    WeasyPrintDocumentRenderer,
)
from eneo.main.exceptions import TypedIOValidationException

logger = logging.getLogger(__name__)


class DocumentRenderService:
    def __init__(
        self,
        renderers: Iterable[DocumentRenderer],
        *,
        limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS,
    ) -> None:
        self._renderers = {renderer.output_type: renderer for renderer in renderers}
        self._limits = limits

    @property
    def limits(self) -> DocumentRenderLimits:
        return self._limits

    def render_document(
        self,
        text: str,
        output_type: str,
        *,
        step_order: int,
    ) -> tuple[bytes, str, str]:
        ensure_source_within_limits(text, limits=self._limits)
        source_text = _unwrap_single_field_text_envelope(
            text,
            step_order=step_order,
        )
        return self.render_blocks(
            parse_markdown_blocks(source_text.splitlines()),
            output_type,
            step_order=step_order,
        )

    def render_structured_document(
        self,
        data: dict[str, Any] | list[Any],
        output_type: str,
        *,
        step_order: int,
        schema: dict[str, Any] | None = None,
    ) -> tuple[bytes, str, str]:
        ensure_structured_value_within_limits(data, limits=self._limits)
        try:
            blocks = structured_data_to_blocks(data, schema=schema)
        except TypedIOValidationException:
            raise
        except Exception as exc:
            _raise_render_failed(
                output_type=output_type, step_order=step_order, exc=exc
            )
        return self.render_blocks(
            blocks,
            output_type,
            step_order=step_order,
        )

    def render_blocks(
        self,
        blocks: Sequence[DocumentBlock],
        output_type: str,
        *,
        step_order: int,
    ) -> tuple[bytes, str, str]:
        ensure_blocks_within_limits(blocks, limits=self._limits)
        renderer = self._renderers.get(output_type)
        if renderer is None:
            raise TypedIOValidationException(
                f"Unsupported document type: {output_type}",
                code=FlowApiErrorCode.TYPED_IO_RENDER_FAILED.value,
            )
        try:
            return renderer.render(blocks, step_order=step_order).as_tuple()
        except TypedIOValidationException:
            raise
        except Exception as exc:
            _raise_render_failed(
                output_type=output_type, step_order=step_order, exc=exc
            )


def default_document_render_service(
    *,
    limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS,
) -> DocumentRenderService:
    return DocumentRenderService(
        renderers=(
            WeasyPrintDocumentRenderer(),
            DocxDocumentRenderer(),
        ),
        limits=limits,
    )


def _unwrap_single_field_text_envelope(text: str, *, step_order: int) -> str:
    """Unwrap a one-field JSON string envelope around document text.

    A text-output writer occasionally wraps its finished markdown in
    ``{"document_body": "..."}``. The wrapper carries no information beyond
    its key, but rendered verbatim it turns the whole document into braces
    and escape sequences. Anything richer than exactly one string field is
    left untouched — unwrapping it would lose structure.
    """

    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return text
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return text
    if not isinstance(parsed, dict):
        return text
    envelope = cast(dict[str, Any], parsed)
    if len(envelope) != 1:
        return text
    ((field_name, value),) = envelope.items()
    if not isinstance(value, str) or not value.strip():
        return text
    logger.info(
        "document_render_single_field_envelope_unwrapped",
        extra={"step_order": step_order, "field_name": field_name},
    )
    return value


def _raise_render_failed(
    *,
    output_type: str,
    step_order: int,
    exc: Exception,
) -> NoReturn:
    logger.exception(
        "Document render failed",
        extra={"output_type": output_type, "step_order": step_order},
    )
    raise TypedIOValidationException(
        "Document render failed.",
        code=FlowApiErrorCode.TYPED_IO_RENDER_FAILED.value,
    ) from exc
