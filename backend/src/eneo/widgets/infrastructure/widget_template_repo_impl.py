# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Any
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.widget_templates_table import WidgetTemplates
from eneo.main.exceptions import NotFoundException
from eneo.widgets.domain.widget import WidgetLanguage, WidgetTexts, WidgetTheme
from eneo.widgets.domain.widget_template import TemplateLockGroup, WidgetTemplate


def _to_entity(row: WidgetTemplates) -> WidgetTemplate:
    return WidgetTemplate(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description or "",
        texts=WidgetTexts.model_validate(row.texts or {}),
        theme=WidgetTheme.model_validate(row.theme or {}),
        language=WidgetLanguage(row.language),
        is_default=bool(row.is_default),
        locked_groups=[TemplateLockGroup(group) for group in (row.locked_groups or [])],
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_values(template: WidgetTemplate) -> dict[str, Any]:
    return {
        "tenant_id": template.tenant_id,
        "name": template.name,
        "description": template.description,
        "texts": template.texts.model_dump(mode="json"),
        "theme": template.theme.model_dump(mode="json"),
        "language": template.language.value,
        "is_default": template.is_default,
        "locked_groups": [group.value for group in template.locked_groups],
        "created_by_user_id": template.created_by_user_id,
    }


class WidgetTemplateRepoImpl:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, template: WidgetTemplate) -> WidgetTemplate:
        stmt = (
            sa.insert(WidgetTemplates)
            .values(**_to_values(template))
            .returning(WidgetTemplates)
        )
        row = await self.session.scalar(stmt)
        assert row is not None
        return _to_entity(row)

    async def get(self, template_id: UUID) -> WidgetTemplate | None:
        row = await self.session.scalar(
            sa.select(WidgetTemplates).where(WidgetTemplates.id == template_id)
        )
        return _to_entity(row) if row is not None else None

    async def list_by_tenant(self, tenant_id: UUID) -> list[WidgetTemplate]:
        rows = await self.session.scalars(
            sa.select(WidgetTemplates)
            .where(WidgetTemplates.tenant_id == tenant_id)
            .order_by(
                WidgetTemplates.is_default.desc(),
                WidgetTemplates.name.asc(),
            )
        )
        return [_to_entity(row) for row in rows]

    async def update(self, template: WidgetTemplate) -> WidgetTemplate:
        if template.id is None:
            raise NotFoundException("Widget template has not been persisted.")
        values = _to_values(template)
        values["updated_at"] = sa.func.now()
        row = await self.session.scalar(
            sa.update(WidgetTemplates)
            .where(WidgetTemplates.id == template.id)
            .values(**values)
            .returning(WidgetTemplates)
        )
        if row is None:
            raise NotFoundException("Widget template not found.")
        return _to_entity(row)

    async def delete(self, template_id: UUID) -> None:
        await self.session.execute(
            sa.delete(WidgetTemplates).where(WidgetTemplates.id == template_id)
        )

    async def clear_default(self, tenant_id: UUID) -> None:
        await self.session.execute(
            sa.update(WidgetTemplates)
            .where(
                WidgetTemplates.tenant_id == tenant_id,
                WidgetTemplates.is_default.is_(True),
            )
            .values(is_default=False, updated_at=sa.func.now())
        )
