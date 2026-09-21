# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from collections.abc import Iterable
from typing import Any, Optional
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.widgets_table import Widgets
from eneo.main.exceptions import NotFoundException
from eneo.widgets.domain.exceptions import WidgetRevisionConflictError
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


def to_entity(row: Widgets) -> Widget:
    return Widget(
        id=row.id,
        public_id=row.public_id,
        tenant_id=row.tenant_id,
        space_id=row.space_id,
        target_type=WidgetTargetType(row.target_type),
        target_id=row.target_id,
        status=WidgetStatus(row.status),
        token_generation=row.token_generation,
        revision=row.revision,
        name=row.name,
        texts=WidgetTexts.model_validate(row.texts or {}),
        theme=WidgetTheme.model_validate(row.theme or {}),
        limits=WidgetLimits.model_validate(row.limits or {}),
        privacy=WidgetPrivacy.model_validate(row.privacy or {}),
        language=WidgetLanguage(row.language),
        allowed_origins=list(row.allowed_origins or []),
        bot_protection=BotProtection(row.bot_protection),
        template_id=row.template_id,
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
        "template_id": widget.template_id,
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
        return to_entity(row)

    async def get(self, widget_id: UUID) -> Widget | None:
        row = await self.session.scalar(
            sa.select(Widgets).where(Widgets.id == widget_id)
        )
        return to_entity(row) if row is not None else None

    async def get_by_public_id(self, public_id: str) -> Widget | None:
        row = await self.session.scalar(
            sa.select(Widgets).where(Widgets.public_id == public_id)
        )
        return to_entity(row) if row is not None else None

    async def list_by_space(self, space_id: UUID) -> list[Widget]:
        rows = await self.session.scalars(
            sa.select(Widgets)
            .where(Widgets.space_id == space_id)
            .order_by(Widgets.created_at.desc())
        )
        return [to_entity(row) for row in rows]

    async def list_by_template(
        self, template_id: UUID, *, include_archived: bool = False
    ) -> list[Widget]:
        """The followers, locked for the rest of the transaction: a template
        publication writes onto them and must not race a concurrent editor.
        Archived widgets are frozen history and follow nothing."""
        stmt = sa.select(Widgets).where(Widgets.template_id == template_id)
        if not include_archived:
            stmt = stmt.where(Widgets.status != WidgetStatus.ARCHIVED.value)
        rows = await self.session.scalars(
            stmt.order_by(Widgets.created_at.asc()).with_for_update()
        )
        return [to_entity(row) for row in rows]

    async def count_by_template(self, tenant_id: UUID) -> dict[UUID, int]:
        rows = await self.session.execute(
            sa.select(Widgets.template_id, sa.func.count())
            .where(
                Widgets.tenant_id == tenant_id,
                Widgets.template_id.is_not(None),
                Widgets.status != WidgetStatus.ARCHIVED.value,
            )
            .group_by(Widgets.template_id)
        )
        return {template_id: int(count) for template_id, count in rows.all()}

    async def is_target_published(self, widget: Widget) -> bool:
        """Whether the assistant behind the widget is still published in its
        space; checked on the visitor surface so an unpublished assistant
        takes its widget offline instead of answering with a permission error."""
        if widget.target_type != WidgetTargetType.ASSISTANT:
            return False
        published = await self.session.scalar(
            sa.select(Assistants.published).where(
                Assistants.id == widget.target_id,
                Assistants.space_id == widget.space_id,
            )
        )
        return bool(published)

    async def update(
        self,
        widget: Widget,
        *,
        check_revision: bool = True,
        only: Optional[Iterable[str]] = None,
    ) -> Widget:
        """Write the widget back, bumping its revision.

        ``check_revision`` is the optimistic lock every configuration change
        uses. Lifecycle commands pass ``check_revision=False`` together with
        ``only`` (the columns they own), so pausing never loses to a
        concurrent autosave and never overwrites its content either.
        """
        if widget.id is None:
            raise NotFoundException("Widget has not been persisted.")
        values = _to_values(widget)
        if only is not None:
            wanted = set(only)
            values = {key: value for key, value in values.items() if key in wanted}
        values["revision"] = Widgets.revision + 1
        values["updated_at"] = sa.func.now()
        stmt = sa.update(Widgets).where(Widgets.id == widget.id)
        if check_revision:
            stmt = stmt.where(Widgets.revision == widget.revision)
        row = await self.session.scalar(stmt.values(**values).returning(Widgets))
        if row is None:
            if check_revision:
                raise WidgetRevisionConflictError()
            raise NotFoundException("Widget not found.")
        return to_entity(row)
