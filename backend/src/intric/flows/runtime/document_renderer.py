"""Stable facade for flow-generated PDF and DOCX artifacts."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from intric.flows.runtime.document_rendering import DocumentRenderService
from intric.flows.runtime.document_rendering.service import (
    default_document_render_service,
)


@lru_cache(maxsize=1)
def _default_render_service() -> DocumentRenderService:
    return default_document_render_service()


def render_document(
    text: str, output_type: str, *, step_order: int
) -> tuple[bytes, str, str]:
    return _default_render_service().render_document(
        text,
        output_type,
        step_order=step_order,
    )


def render_structured_document(
    data: dict[str, Any] | list[Any],
    output_type: str,
    *,
    step_order: int,
    schema: dict[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    return _default_render_service().render_structured_document(
        data,
        output_type,
        step_order=step_order,
        schema=schema,
    )
