# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from collections.abc import Iterable
from typing import Optional, Protocol
from uuid import UUID

from eneo.widgets.domain.widget import BotProtection, Widget
from eneo.widgets.domain.widget_policy import WidgetPolicy


class WidgetRepo(Protocol):
    async def add(self, widget: Widget) -> Widget: ...

    async def get(
        self, widget_id: UUID, *, for_update: bool = False
    ) -> Widget | None: ...

    async def get_by_public_id(self, public_id: str) -> Widget | None:
        """The widget as the visitor surface serves it: within its tenant's
        widget policy (``WidgetPolicy.serving``). Never write it back."""
        ...

    async def policy_for(self, tenant_id: UUID) -> WidgetPolicy: ...

    async def revoke_tokens(
        self, tenant_id: UUID, *, bot_protection: BotProtection
    ) -> int:
        """Bump the token generation of the tenant's live widgets that use
        ``bot_protection``; returns how many changed."""
        ...

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
