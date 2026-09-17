# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Protocol
from uuid import UUID

from eneo.widgets.domain.widget import Widget


class WidgetRepo(Protocol):
    async def add(self, widget: Widget) -> Widget: ...

    async def get(self, widget_id: UUID) -> Widget | None: ...

    async def get_by_public_id(self, public_id: str) -> Widget | None: ...

    async def list_by_space(self, space_id: UUID) -> list[Widget]: ...

    async def update(self, widget: Widget) -> Widget: ...
