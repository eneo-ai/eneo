"""Persistence for document templates and the assistants that select them."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from eneo.database.tables.document_templates_table import (
    AssistantDocumentTemplates,
    DocumentTemplates,
)
from eneo.document_templates.domain import (
    DocumentTemplate,
    DocumentTemplateChoice,
    DocumentTemplateStatus,
    TemplateSyntax,
)


def _to_domain(row: DocumentTemplates, selected_by: int = 0) -> DocumentTemplate:
    return DocumentTemplate(
        id=row.id,
        tenant_id=row.tenant_id,
        space_id=row.space_id,
        name=row.name,
        filename=row.filename,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        syntax=cast(TemplateSyntax, row.syntax),
        placeholders=list(row.placeholders or []),
        checks=dict(row.checks or {}),
        status=cast(DocumentTemplateStatus, row.status),
        is_default=row.is_default,
        created_by=row.created_by,
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        selected_by=selected_by,
    )


class DocumentTemplateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _live(self, tenant_id: UUID):
        return sa.select(DocumentTemplates).where(
            DocumentTemplates.tenant_id == tenant_id,
            DocumentTemplates.deleted_at.is_(None),
        )

    async def list(self, tenant_id: UUID) -> list[DocumentTemplate]:
        selected = (
            sa.select(
                AssistantDocumentTemplates.document_template_id.label("template_id"),
                sa.func.count().label("count"),
            )
            .where(AssistantDocumentTemplates.document_template_id.is_not(None))
            .group_by(AssistantDocumentTemplates.document_template_id)
            .subquery()
        )
        query = (
            sa.select(DocumentTemplates, sa.func.coalesce(selected.c.count, 0))
            .outerjoin(selected, selected.c.template_id == DocumentTemplates.id)
            .where(
                DocumentTemplates.tenant_id == tenant_id,
                DocumentTemplates.deleted_at.is_(None),
            )
            .order_by(
                DocumentTemplates.is_default.desc(),
                DocumentTemplates.name,
            )
        )
        rows = (await self.session.execute(query)).all()
        return [_to_domain(row[0], int(row[1])) for row in rows]

    async def get(self, tenant_id: UUID, template_id: UUID) -> DocumentTemplate | None:
        row = await self.session.scalar(
            self._live(tenant_id).where(DocumentTemplates.id == template_id)
        )
        return _to_domain(row) if row is not None else None

    async def get_default(self, tenant_id: UUID) -> DocumentTemplate | None:
        row = await self.session.scalar(
            self._live(tenant_id).where(DocumentTemplates.is_default.is_(True))
        )
        return _to_domain(row) if row is not None else None

    async def get_content(
        self, tenant_id: UUID, template_id: UUID
    ) -> tuple[DocumentTemplate, bytes] | None:
        row = await self.session.scalar(
            self._live(tenant_id)
            .where(DocumentTemplates.id == template_id)
            .options(undefer(DocumentTemplates.content))
            # A row the session already holds gets its deferred bytes this way.
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        return _to_domain(row), bytes(row.content)

    async def name_taken(
        self, tenant_id: UUID, name: str, except_id: UUID | None
    ) -> bool:
        query = self._live(tenant_id).where(
            sa.func.lower(DocumentTemplates.name) == name.lower()
        )
        if except_id is not None:
            query = query.where(DocumentTemplates.id != except_id)
        return (await self.session.scalar(query)) is not None

    async def create(
        self,
        *,
        tenant_id: UUID,
        name: str,
        filename: str,
        content: bytes,
        sha256: str,
        syntax: TemplateSyntax,
        placeholders: list[dict[str, Any]],
        checks: dict[str, Any],
        status: DocumentTemplateStatus,
        is_default: bool,
        user_id: UUID | None,
    ) -> DocumentTemplate:
        if is_default:
            await self._clear_default(tenant_id)
        row = DocumentTemplates(
            tenant_id=tenant_id,
            name=name,
            filename=filename,
            content=content,
            sha256=sha256,
            size_bytes=len(content),
            syntax=syntax,
            placeholders=placeholders,
            checks=checks,
            status=status,
            is_default=is_default,
            created_by=user_id,
            updated_by=user_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return _to_domain(row)

    async def update(
        self,
        tenant_id: UUID,
        template_id: UUID,
        *,
        user_id: UUID | None,
        name: str | None = None,
        is_default: bool | None = None,
        content: tuple[str, bytes, str] | None = None,
        inspection: tuple[TemplateSyntax, list[dict[str, Any]], dict[str, Any], str]
        | None = None,
    ) -> DocumentTemplate | None:
        row = await self.session.scalar(
            self._live(tenant_id).where(DocumentTemplates.id == template_id)
        )
        if row is None:
            return None
        if name is not None:
            row.name = name
        if is_default is True:
            await self._clear_default(tenant_id, except_id=template_id)
            row.is_default = True
        elif is_default is False:
            row.is_default = False
        if content is not None:
            row.filename, row.content, row.sha256 = content
            row.size_bytes = len(content[1])
        if inspection is not None:
            row.syntax, row.placeholders, row.checks, row.status = inspection
        row.updated_by = user_id
        await self.session.flush()
        await self.session.refresh(row)
        return _to_domain(row)

    async def _clear_default(
        self, tenant_id: UUID, except_id: UUID | None = None
    ) -> None:
        query = (
            sa.update(DocumentTemplates)
            .where(
                DocumentTemplates.tenant_id == tenant_id,
                DocumentTemplates.is_default.is_(True),
            )
            .values(is_default=False)
        )
        if except_id is not None:
            query = query.where(DocumentTemplates.id != except_id)
        await self.session.execute(query)

    async def soft_delete(
        self, tenant_id: UUID, template_id: UUID, *, user_id: UUID | None
    ) -> DocumentTemplate | None:
        row = await self.session.scalar(
            self._live(tenant_id).where(DocumentTemplates.id == template_id)
        )
        if row is None:
            return None
        row.deleted_at = datetime.now(timezone.utc)
        row.is_default = False
        row.updated_by = user_id
        # Assistants that selected it fall back to the organisation's default.
        await self.session.execute(
            sa.delete(AssistantDocumentTemplates).where(
                AssistantDocumentTemplates.document_template_id == template_id
            )
        )
        await self.session.flush()
        await self.session.refresh(row)
        return _to_domain(row)

    async def choice_for_assistant(self, assistant_id: UUID) -> DocumentTemplateChoice:
        row = (
            await self.session.execute(
                sa.select(
                    AssistantDocumentTemplates.mode,
                    AssistantDocumentTemplates.document_template_id,
                ).where(AssistantDocumentTemplates.assistant_id == assistant_id)
            )
        ).first()
        if row is None:
            return DocumentTemplateChoice()
        try:
            mode = cast(Literal["default", "selected", "builtin"], row[0])
            return DocumentTemplateChoice(mode=mode, template_id=row[1])
        except ValueError:
            return DocumentTemplateChoice()
