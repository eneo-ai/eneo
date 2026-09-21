# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from collections.abc import Iterable
from typing import Optional, Protocol
from uuid import UUID

from eneo.widgets.domain.widget import Widget


class WidgetRepo(Protocol):
    async def add(self, widget: Widget) -> Widget: ...

    async def get(
        self, widget_id: UUID, *, for_update: bool = False
    ) -> Widget | None: ...

    async def get_by_public_id(self, public_id: str) -> Widget | None: ...

    async def list_by_space(self, space_id: UUID) -> list[Widget]: ...

    async def list_by_template(
        self, template_id: UUID, *, include_archived: bool = False
    ) -> list[Widget]: ...

    async def count_by_template(self, tenant_id: UUID) -> dict[UUID, int]: ...

    async def is_target_published(self, widget: Widget) -> bool: ...

    async def update(
        self,
        widget: Widget,
        *,
        check_revision: bool = True,
        only: Optional[Iterable[str]] = None,
    ) -> Widget: ...
