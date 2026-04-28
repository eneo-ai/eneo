from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any, NoReturn

from intric.flows.runtime.document_rendering.blocks import DocumentBlock
from intric.flows.runtime.document_rendering.docx_renderer import DocxDocumentRenderer
from intric.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
    ensure_blocks_within_limits,
    ensure_source_within_limits,
    ensure_structured_value_within_limits,
)
from intric.flows.runtime.document_rendering.markdown_blocks import (
    parse_markdown_blocks,
)
from intric.flows.runtime.document_rendering.renderers import DocumentRenderer
from intric.flows.runtime.document_rendering.structured_blocks import (
    structured_data_to_blocks,
)
from intric.flows.runtime.document_rendering.weasyprint_renderer import (
    WeasyPrintDocumentRenderer,
)
from intric.main.exceptions import TypedIOValidationException

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
        return self.render_blocks(
            parse_markdown_blocks(text.splitlines()),
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
                code="typed_io_render_failed",
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
        code="typed_io_render_failed",
    ) from exc
