"""Document templates: the Word files generated documents are rendered into."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

DocumentTemplateMode = Literal["default", "selected", "builtin"]
DocumentTemplateStatus = Literal["ready", "invalid", "unchecked"]
TemplateSyntax = Literal["controls", "braces", "mixed", "none", "unknown"]

# The built-in template is never a row; this names it in references and audits.
BUILTIN_TEMPLATE_NAME = "Eneo"


@dataclass(frozen=True, slots=True)
class DocumentTemplateChoice:
    """An assistant's choice for its file-creation capability."""

    mode: DocumentTemplateMode = "default"
    template_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.mode == "selected") != (self.template_id is not None):
            raise ValueError("A selected template needs an id, and only then")

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "template_id": str(self.template_id) if self.template_id else None,
        }


@dataclass(slots=True)
class DocumentTemplate:
    id: UUID
    tenant_id: UUID
    name: str
    filename: str
    sha256: str
    size_bytes: int
    syntax: TemplateSyntax
    placeholders: list[dict[str, Any]]
    checks: dict[str, Any]
    status: DocumentTemplateStatus
    is_default: bool
    created_at: datetime
    updated_at: datetime
    space_id: UUID | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None
    # How many assistants select this template explicitly (listings only).
    selected_by: int = 0


@dataclass(frozen=True, slots=True)
class DocumentTemplateReference:
    """The template a turn or an export renders with, as the runtime receives it.

    ``url`` and ``filename`` are the signed reference the tool is given; both
    are None for the built-in template, which the runtime applies on its own.
    """

    name: str
    source: Literal["tenant", "assistant", "builtin"]
    template_id: UUID | None = None
    url: str | None = None
    filename: str | None = None

    @property
    def argument(self) -> dict[str, str] | None:
        if self.url is None or self.filename is None:
            return None
        return {"url": self.url, "filename": self.filename}


BUILTIN_REFERENCE = DocumentTemplateReference(
    name=BUILTIN_TEMPLATE_NAME, source="builtin"
)


@dataclass(frozen=True, slots=True)
class TemplateInspection:
    """What the tool runtime read from an uploaded template."""

    syntax: TemplateSyntax
    placeholders: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    checks: dict[str, Any] = field(default_factory=dict[str, Any])
    language: str | None = None
