from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from intric.flows.runtime.document_rendering.blocks import DocumentBlock


@dataclass(frozen=True)
class RenderedDocument:
    blob: bytes
    mimetype: str
    filename: str

    def as_tuple(self) -> tuple[bytes, str, str]:
        return self.blob, self.mimetype, self.filename


class DocumentRenderer(Protocol):
    output_type: str

    def render(
        self,
        blocks: Sequence[DocumentBlock],
        *,
        step_order: int,
    ) -> RenderedDocument: ...
