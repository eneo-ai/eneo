from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, cast

from eneo.document_templates import runtime_client
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.document_rendering.blocks import (
    DocumentBlock,
    normalize_document_headings,
)
from eneo.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
    ensure_blocks_within_limits,
    ensure_source_within_limits,
    ensure_structured_value_within_limits,
)
from eneo.flows.runtime.document_rendering.markdown_blocks import parse_markdown_blocks
from eneo.flows.runtime.document_rendering.structured_blocks import (
    structured_data_to_blocks,
)
from eneo.main.exceptions import BadRequestException, TypedIOValidationException
from eneo.main.logging import get_logger

logger = get_logger(__name__)


class DocumentRenderService:
    """Flow-specific admission/projection; the shared runtime owns all rendering."""

    def __init__(
        self, *, limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS
    ) -> None:
        self._limits = limits

    @property
    def limits(self) -> DocumentRenderLimits:
        return self._limits

    async def render_document(
        self, text: str, output_type: str, *, step_order: int, title: str
    ) -> tuple[bytes, str]:
        ensure_source_within_limits(text, limits=self._limits)
        source = _unwrap_single_field_text_envelope(text, step_order=step_order)
        return await self.render_blocks(
            parse_markdown_blocks(source.splitlines()),
            output_type,
            step_order=step_order,
            title=title,
        )

    async def render_structured_document(
        self,
        data: dict[str, Any] | list[Any],
        output_type: str,
        *,
        step_order: int,
        title: str,
        schema: dict[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        ensure_structured_value_within_limits(data, limits=self._limits)
        return await self.render_blocks(
            structured_data_to_blocks(data, schema=schema),
            output_type,
            step_order=step_order,
            title=title,
        )

    async def render_blocks(
        self,
        blocks: Sequence[DocumentBlock],
        output_type: str,
        *,
        step_order: int,
        title: str,
    ) -> tuple[bytes, str]:
        from eneo.flows.runtime.document_rendering.markdown_projection import (
            blocks_to_markdown,
        )

        blocks = normalize_document_headings(list(blocks))
        ensure_blocks_within_limits(blocks, limits=self._limits)
        return await self._render(blocks_to_markdown(blocks), output_type, title)

    async def _render(
        self, content: str, output_type: str, title: str
    ) -> tuple[bytes, str]:
        if output_type not in {"docx", "pdf"}:
            raise TypedIOValidationException(
                "Unsupported document type.",
                code=FlowApiErrorCode.TYPED_IO_RENDER_FAILED.value,
            )
        try:
            return await runtime_client.render_document(
                content=content, title=title, output_type=output_type
            )
        except BadRequestException as exc:
            raise TypedIOValidationException(
                "The document could not be rendered within its limits.",
                code=FlowApiErrorCode.TYPED_IO_RENDER_FAILED.value,
            ) from exc
        except runtime_client.RuntimeUnavailable as exc:
            raise TypedIOValidationException(
                "The shared document runtime is unavailable.",
                code=FlowApiErrorCode.TYPED_IO_RENDER_FAILED.value,
            ) from exc


def default_document_render_service(
    *, limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS
) -> DocumentRenderService:
    return DocumentRenderService(limits=limits)


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
