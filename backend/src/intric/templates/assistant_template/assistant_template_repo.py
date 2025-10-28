from typing import TYPE_CHECKING, Optional
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import or_, func, update

from intric.database.tables.assistant_template_table import AssistantTemplates

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.templates.assistant_template.api.assistant_template_models import (
        AssistantTemplateCreate,
        AssistantTemplateUpdate,
    )
    from intric.templates.assistant_template.assistant_template import AssistantTemplate
    from intric.templates.assistant_template.assistant_template_factory import (
        AssistantTemplateFactory,
    )


class AssistantTemplateRepository:
    def __init__(self, session: "AsyncSession", factory: "AssistantTemplateFactory"):
        self.session = session
        self.factory = factory

        self._db_model = AssistantTemplates
        # db relations
        self._options = [selectinload(self._db_model.completion_model)]

    def _apply_options(self, query: "Select") -> "Select":
        for option in self._options:
            query = query.options(option)

        return query

    async def get_by_id(
        self, assistant_template_id: "UUID", tenant_id: Optional["UUID"] = None
    ) -> Optional["AssistantTemplate"]:
        """Get template by ID.

        If tenant_id provided:
          - Filter by: id AND tenant_id AND deleted_at IS NULL
          - Returns: Only if belongs to tenant

        If tenant_id is None:
          - Filter by: id AND deleted_at IS NULL
          - Returns: Template regardless of tenant_id (used for internal queries)
        """
        base_query = select(self._db_model).where(
            self._db_model.id == assistant_template_id,
            self._db_model.deleted_at.is_(None)
        )

        if tenant_id is not None:
            base_query = base_query.where(self._db_model.tenant_id == tenant_id)

        query = self._apply_options(query=base_query)

        record = await self.session.scalar(query)

        if not record:
            return None

        return self.factory.create_assistant_template(item=record)

    async def get_assistant_template_list(self, tenant_id: Optional["UUID"] = None) -> list["AssistantTemplate"]:
        """Get all active templates.

        If tenant_id provided:
          - Return templates WHERE (tenant_id = ? OR tenant_id IS NULL) AND deleted_at IS NULL
          - Includes both tenant-specific and global templates

        If tenant_id is None:
          - Return templates WHERE tenant_id IS NULL AND deleted_at IS NULL
          - Global templates only
        """
        base_query = select(self._db_model).where(
            self._db_model.deleted_at.is_(None)
        )

        if tenant_id is not None:
            base_query = base_query.where(
                or_(
                    self._db_model.tenant_id == tenant_id,
                    self._db_model.tenant_id.is_(None)
                )
            )
        else:
            base_query = base_query.where(self._db_model.tenant_id.is_(None))

        query = self._apply_options(query=base_query)

        results = await self.session.scalars(query)

        return self.factory.create_assistant_template_list(items=results.all())

    async def add(self, obj: "AssistantTemplateCreate") -> "AssistantTemplate":
        stmt = (
            sa.insert(AssistantTemplates)
            .values(
                name=obj.name,
                description=obj.description,
                category=obj.category,
                prompt_text=obj.prompt,
                wizard=obj.wizard.model_dump(),
                completion_model_kwargs=obj.completion_model_kwargs,
            )
            .returning(AssistantTemplates)
        )
        result = await self.session.execute(stmt)
        template = result.scalar_one()

        return self.factory.create_assistant_template(item=template)

    async def delete(self, id: "UUID") -> None:
        stmt = sa.delete(self._db_model).where(self._db_model.id == id)
        await self.session.execute(stmt)

    async def update(
        self,
        id: "UUID",
        obj: "AssistantTemplateUpdate",
    ) -> "AssistantTemplate":
        stmt = (
            sa.update(self._db_model)
            .values(
                name=obj.name,
                description=obj.description,
                category=obj.category,
                prompt_text=obj.prompt,
                organization=obj.organization,
                wizard=obj.wizard.model_dump(),
            )
            .where(self._db_model.id == id)
            .returning(self._db_model)
        )
        result = await self.session.execute(stmt)
        template_updated = result.scalar_one()
        return self.factory.create_assistant_template(item=template_updated)

    async def get_for_tenant(self, tenant_id: "UUID") -> list["AssistantTemplate"]:
        """Get tenant-owned templates only (admin view).

        Returns templates WHERE tenant_id = ? AND deleted_at IS NULL
        Excludes global templates (tenant_id IS NULL).
        Used for admin management page.
        """
        base_query = select(self._db_model).where(
            self._db_model.tenant_id == tenant_id,
            self._db_model.deleted_at.is_(None)
        )
        query = self._apply_options(query=base_query)
        results = await self.session.scalars(query)
        return self.factory.create_assistant_template_list(items=results.all())

    async def check_duplicate_name(self, name: str, tenant_id: Optional["UUID"] = None) -> bool:
        """Check if template name already exists.

        If tenant_id provided:
          - Check: name exists for this tenant (tenant_id = ?) AND NOT deleted

        If tenant_id is None:
          - Check: name exists globally (tenant_id IS NULL) AND NOT deleted

        Returns True if duplicate exists, False otherwise.
        """
        query = select(func.count(self._db_model.id)).where(
            self._db_model.name == name,
            self._db_model.deleted_at.is_(None)
        )
        if tenant_id is not None:
            query = query.where(self._db_model.tenant_id == tenant_id)
        else:
            query = query.where(self._db_model.tenant_id.is_(None))

        count = await self.session.scalar(query)
        return count > 0

    async def soft_delete(self, id: "UUID", tenant_id: "UUID", user_id: "UUID") -> "AssistantTemplate":
        """Soft-delete template (mark with deleted_at).

        Validates: template belongs to tenant
        """
        stmt = (
            update(self._db_model)
            .where(
                self._db_model.id == id,
                self._db_model.tenant_id == tenant_id
            )
            .values(
                deleted_at=datetime.now(timezone.utc),
                deleted_by_user_id=user_id
            )
            .returning(self._db_model)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        record = result.scalar_one_or_none()

        if not record:
            return None

        return self.factory.create_assistant_template(item=record)

    async def restore(self, id: "UUID", tenant_id: "UUID", user_id: "UUID") -> "AssistantTemplate":
        """Restore soft-deleted template (clear deleted_at).

        Validates: template belongs to tenant and is deleted
        """
        stmt = (
            update(self._db_model)
            .where(
                self._db_model.id == id,
                self._db_model.tenant_id == tenant_id,
                self._db_model.deleted_at.is_not(None)
            )
            .values(
                deleted_at=None,
                restored_by_user_id=user_id,
                restored_at=datetime.now(timezone.utc)
            )
            .returning(self._db_model)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        record = result.scalar_one_or_none()

        if not record:
            return None

        return self.factory.create_assistant_template(item=record)

    async def permanent_delete(self, id: "UUID", tenant_id: "UUID") -> bool:
        """Permanently delete a template from the database (hard delete).

        Validates: template belongs to tenant and is soft-deleted
        Returns: True if deleted, False if not found
        """
        from sqlalchemy import delete

        stmt = (
            delete(self._db_model)
            .where(
                self._db_model.id == id,
                self._db_model.tenant_id == tenant_id,
                self._db_model.deleted_at.is_not(None)  # Only hard-delete soft-deleted items
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()

        return result.rowcount > 0

    async def get_deleted_for_tenant(self, tenant_id: "UUID") -> list["AssistantTemplate"]:
        """Get soft-deleted templates for audit trail view.

        Returns templates WHERE tenant_id = ? AND deleted_at IS NOT NULL
        Ordered by deleted_at DESC (most recently deleted first)
        """
        base_query = select(self._db_model).where(
            self._db_model.tenant_id == tenant_id,
            self._db_model.deleted_at.is_not(None)
        ).order_by(self._db_model.deleted_at.desc())

        query = self._apply_options(query=base_query)
        results = await self.session.scalars(query)
        return self.factory.create_assistant_template_list(items=results.all())
