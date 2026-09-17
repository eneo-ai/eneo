# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Any
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.widgets_table import Widgets
from eneo.main.exceptions import NotFoundException
from eneo.widgets.domain.widget import (
    BotProtection,
    Widget,
    WidgetLanguage,
    WidgetLimits,
    WidgetPrivacy,
    WidgetStatus,
    WidgetTargetType,
    WidgetTexts,
    WidgetTheme,
)


def _to_entity(row: Widgets) -> Widget:
    return Widget(
        id=row.id,
        public_id=row.public_id,
        tenant_id=row.tenant_id,
        space_id=row.space_id,
        target_type=WidgetTargetType(row.target_type),
        target_id=row.target_id,
        status=WidgetStatus(row.status),
        token_generation=row.token_generation,
        name=row.name,
        texts=WidgetTexts.model_validate(row.texts or {}),
        theme=WidgetTheme.model_validate(row.theme or {}),
        limits=WidgetLimits.model_validate(row.limits or {}),
        privacy=WidgetPrivacy.model_validate(row.privacy or {}),
        language=WidgetLanguage(row.language),
        allowed_origins=list(row.allowed_origins or []),
        bot_protection=BotProtection(row.bot_protection),
        created_by_user_id=row.created_by_user_id,
        activated_by_user_id=row.activated_by_user_id,
        activated_at=row.activated_at,
        paused_at=row.paused_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_values(widget: Widget) -> dict[str, Any]:
    return {
        "public_id": widget.public_id,
        "tenant_id": widget.tenant_id,
        "space_id": widget.space_id,
        "target_type": widget.target_type.value,
        "target_id": widget.target_id,
        "status": widget.status.value,
        "token_generation": widget.token_generation,
        "name": widget.name,
        "texts": widget.texts.model_dump(mode="json"),
        "theme": widget.theme.model_dump(mode="json"),
        "limits": widget.limits.model_dump(mode="json"),
        "privacy": widget.privacy.model_dump(mode="json"),
        "language": widget.language.value,
        "allowed_origins": list(widget.allowed_origins),
        "bot_protection": widget.bot_protection.value,
        "created_by_user_id": widget.created_by_user_id,
        "activated_by_user_id": widget.activated_by_user_id,
        "activated_at": widget.activated_at,
        "paused_at": widget.paused_at,
    }


class WidgetRepoImpl:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, widget: Widget) -> Widget:
        stmt = sa.insert(Widgets).values(**_to_values(widget)).returning(Widgets)
        row = await self.session.scalar(stmt)
        assert row is not None
        return _to_entity(row)

    async def get(self, widget_id: UUID) -> Widget | None:
        row = await self.session.scalar(
            sa.select(Widgets).where(Widgets.id == widget_id)
        )
        return _to_entity(row) if row is not None else None

    async def get_by_public_id(self, public_id: str) -> Widget | None:
        row = await self.session.scalar(
            sa.select(Widgets).where(Widgets.public_id == public_id)
        )
        return _to_entity(row) if row is not None else None

    async def list_by_space(self, space_id: UUID) -> list[Widget]:
        rows = await self.session.scalars(
            sa.select(Widgets)
            .where(Widgets.space_id == space_id)
            .order_by(Widgets.created_at.desc())
        )
        return [_to_entity(row) for row in rows]

    async def update(self, widget: Widget) -> Widget:
        if widget.id is None:
            raise NotFoundException("Widget has not been persisted.")
        values = _to_values(widget)
        values["updated_at"] = sa.func.now()
        stmt = (
            sa.update(Widgets)
            .where(Widgets.id == widget.id)
            .values(**values)
            .returning(Widgets)
        )
        row = await self.session.scalar(stmt)
        if row is None:
            raise NotFoundException("Widget not found.")
        return _to_entity(row)
