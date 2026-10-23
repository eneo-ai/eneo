"""API models for the document template library."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.document_templates.domain import DocumentTemplate

DocumentTemplateModeLiteral = Literal["default", "selected", "builtin"]


class TemplatePlaceholderPublic(BaseModel):
    name: str
    syntax: Literal["control", "braces"]
    kind: Literal["rich", "text"]
    label: str | None = None
    hint: str | None = None
    location: Literal["body", "header", "footer"]
    supported: bool
    reason: str | None = None


class TemplateCheckPublic(BaseModel):
    ok: bool
    detail: str


class DocumentTemplatePublic(BaseModel):
    id: UUID
    name: str
    filename: str
    sha256: str
    size_bytes: int
    syntax: Literal["controls", "braces", "mixed", "none", "unknown"]
    placeholders: list[TemplatePlaceholderPublic]
    checks: dict[str, TemplateCheckPublic]
    status: Literal["ready", "invalid", "unchecked"]
    is_default: bool
    selected_by: int = Field(
        description="How many assistants select this template explicitly."
    )
    created_by: UUID | None = None
    updated_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, template: DocumentTemplate) -> "DocumentTemplatePublic":
        placeholders: list[TemplatePlaceholderPublic] = []
        for raw in template.placeholders:
            try:
                placeholders.append(TemplatePlaceholderPublic.model_validate(raw))
            except ValueError:
                continue
        checks: dict[str, TemplateCheckPublic] = {}
        for name, raw_check in template.checks.items():
            try:
                checks[name] = TemplateCheckPublic.model_validate(raw_check)
            except ValueError:
                continue
        return cls(
            id=template.id,
            name=template.name,
            filename=template.filename,
            sha256=template.sha256,
            size_bytes=template.size_bytes,
            syntax=template.syntax,
            placeholders=placeholders,
            checks=checks,
            status=template.status,
            is_default=template.is_default,
            selected_by=template.selected_by,
            created_by=template.created_by,
            updated_by=template.updated_by,
            created_at=template.created_at,
            updated_at=template.updated_at,
        )


class DocumentTemplateOptionPublic(BaseModel):
    """A template as an assistant editor picks it: name and default only."""

    id: UUID
    name: str
    is_default: bool


class DocumentTemplateOptions(BaseModel):
    items: list[DocumentTemplateOptionPublic]


class DocumentTemplateList(BaseModel):
    items: list[DocumentTemplatePublic]
    runtime_configured: bool = Field(
        description="Whether uploads are inspected by the tool runtime."
    )


class DocumentTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_default: bool | None = None


class DocumentTemplateChoicePublic(BaseModel):
    """An assistant's choice for its file-creation capability."""

    mode: DocumentTemplateModeLiteral = "default"
    template_id: UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "template_id": self.template_id}


class DocumentTemplateReferencePublic(BaseModel):
    """Which template applies, for display next to an export."""

    name: str
    source: Literal["tenant", "assistant", "builtin"]
    template_id: UUID | None = None
