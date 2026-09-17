# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Protocol
from uuid import UUID

from eneo.widgets.domain.widget_template import WidgetTemplate


class WidgetTemplateRepo(Protocol):
    async def add(self, template: WidgetTemplate) -> WidgetTemplate: ...

    async def get(self, template_id: UUID) -> WidgetTemplate | None: ...

    async def list_by_tenant(self, tenant_id: UUID) -> list[WidgetTemplate]: ...

    async def update(self, template: WidgetTemplate) -> WidgetTemplate: ...

    async def delete(self, template_id: UUID) -> None: ...

    async def clear_default(self, tenant_id: UUID) -> None: ...
