from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from eneo.flows.runtime.document_rendering.blocks import DocumentBlock


@dataclass(frozen=True)
class RenderedDocument:
    blob: bytes
    mimetype: str

    def as_tuple(self) -> tuple[bytes, str]:
        return self.blob, self.mimetype


class DocumentRenderer(Protocol):
    output_type: str

    def render(
        self,
        blocks: Sequence[DocumentBlock],
        *,
        title: str,
    ) -> RenderedDocument: ...
