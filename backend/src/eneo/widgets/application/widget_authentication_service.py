# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Live authorization for public widget requests and delegated internal tools."""

from typing import TYPE_CHECKING
from uuid import UUID

from eneo.main.exceptions import NotFoundException, TenantSuspendedException
from eneo.widgets.application.visitor_token_service import VisitorTokenService
from eneo.widgets.application.visitor_user import build_visitor_user
from eneo.widgets.domain.exceptions import (
    VisitorTokenInvalidError,
    VisitorTokenStaleError,
    WidgetNotActiveError,
    WidgetPublicError,
)
from eneo.widgets.domain.visitor import WidgetVisitorContext
from eneo.widgets.domain.widget import Widget, WidgetStatus, is_public_id
from eneo.widgets.domain.widget_repo import WidgetRepo

if TYPE_CHECKING:
    from eneo.tenants.tenant_repo import TenantRepository
    from eneo.users.user import UserInDB
    from eneo.users.user_service import UserService


class WidgetAuthenticationService:
    def __init__(
        self,
        widget_repo: WidgetRepo,
        tenant_repo: "TenantRepository",
        user_service: "UserService",
        visitor_tokens: VisitorTokenService,
    ) -> None:
        self.widget_repo = widget_repo
        self.tenant_repo = tenant_repo
        self.user_service = user_service
        self.visitor_tokens = visitor_tokens

    async def _require_available(self, widget: Widget, *, preview: bool) -> None:
        if widget.status == WidgetStatus.ACTIVE:
            if await self.widget_repo.is_target_published(widget):
                return
        elif widget.status != WidgetStatus.ARCHIVED and preview:
            return
        raise WidgetNotActiveError()

    async def get_active_widget(
        self, public_id: str, *, preview_token: str | None = None
    ) -> Widget:
        """Unknown, unpublished and inactive widgets share the same public 404."""
        if not is_public_id(public_id):
            raise WidgetNotActiveError()
        widget = await self.widget_repo.get_by_public_id(public_id)
        if widget is None:
            raise WidgetNotActiveError()
        preview = False
        if preview_token is not None and widget.status != WidgetStatus.ACTIVE:
            try:
                preview = self.visitor_tokens.verify(preview_token, widget).preview
            except WidgetPublicError:
                pass
        await self._require_available(widget, preview=preview)
        return widget

    async def resolve_user(
        self, widget: Widget, visitor_id: UUID, *, preview: bool = False
    ) -> "UserInDB":
        """Build a permissionless visitor using the organisation's live state."""
        tenant = await self.tenant_repo.get(widget.tenant_id)
        if tenant is None:
            raise NotFoundException("Tenant not found.")
        user = build_visitor_user(widget, visitor_id, tenant, preview=preview)
        try:
            await self.user_service.validate_active_identity(
                user, correlation_id="widget-visitor"
            )
        except TenantSuspendedException as exc:
            raise WidgetNotActiveError() from exc
        return user

    async def authenticate_internal(
        self, scope: WidgetVisitorContext, *, assistant_id: UUID
    ) -> "UserInDB":
        """Revalidate a signed delegation; never resolve it as an account.

        The caller must verify the internal MCP signature/audience/expiry
        first. Live scope and generation checks keep a running completion
        from using an old grant after the widget is changed or revoked.
        """
        widget = await self.widget_repo.get(scope.widget_id)
        if widget is None:
            raise WidgetNotActiveError()
        if (
            widget.tenant_id != scope.tenant_id
            or widget.space_id != scope.space_id
            or widget.target_id != scope.target_id
            or assistant_id != widget.target_id
        ):
            raise VisitorTokenInvalidError("Internal tool scope does not match widget.")
        if widget.token_generation != scope.token_generation:
            raise VisitorTokenStaleError()
        await self._require_available(widget, preview=scope.preview)
        return await self.resolve_user(widget, scope.visitor_id, preview=scope.preview)
