# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import ValidationError

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission, validate_permission
from eneo.users.user import UserInDB
from eneo.widgets.domain.widget import (
    Widget,
    WidgetLanguage,
    WidgetStatus,
    WidgetTargetType,
)
from eneo.widgets.domain.widget_policy import WidgetPolicy
from eneo.widgets.domain.widget_repo import WidgetRepo

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.spaces.space import Space
    from eneo.spaces.space_service import SpaceService
    from eneo.tenants.tenant_service import TenantService


@dataclass(frozen=True)
class WidgetView:
    widget: Widget
    activation_blockers: list[str]


class WidgetService:
    def __init__(
        self,
        user: UserInDB,
        repo: WidgetRepo,
        space_service: "SpaceService",
        actor_manager: "ActorManager",
        tenant_service: "TenantService",
    ) -> None:
        self.user = user
        self.repo = repo
        self.space_service = space_service
        self.actor_manager = actor_manager
        self.tenant_service = tenant_service

    # --- policy -----------------------------------------------------------

    def get_policy(self) -> WidgetPolicy:
        return WidgetPolicy.from_tenant(self.user.tenant.widget_policy)

    def read_policy(self) -> WidgetPolicy:
        """Admin-facing read; editors only ever see the policy through blockers."""
        validate_permission(self.user, Permission.ADMIN)
        return self.get_policy()

    async def update_policy(self, updates: dict[str, Any]) -> WidgetPolicy:
        validate_permission(self.user, Permission.ADMIN)
        merged = dict(self.user.tenant.widget_policy or {})
        merged.update(updates)
        # Validate the merged document before persisting so a partial update
        # can never leave the tenant with an inconsistent window.
        try:
            policy = WidgetPolicy.from_tenant(merged)
        except ValidationError as exc:
            messages = "; ".join(str(e.get("msg", e)) for e in exc.errors())
            raise BadRequestException(f"Invalid widget policy: {messages}") from exc
        tenant = await self.tenant_service.update_widget_policy(
            self.user.tenant_id, policy.model_dump(mode="json")
        )
        return WidgetPolicy.from_tenant(tenant.widget_policy)

    # --- helpers ----------------------------------------------------------

    async def _space_for_edit(self, space_id: UUID) -> "Space":
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to manage widgets in this space."
            )
        return space

    async def _owned_widget(self, widget_id: UUID) -> Widget:
        widget = await self.repo.get(widget_id)
        if widget is None or widget.tenant_id != self.user.tenant_id:
            raise NotFoundException("Widget not found.")
        return widget

    @staticmethod
    def _target_published(space: "Space", widget: Widget) -> bool:
        if widget.target_type != WidgetTargetType.ASSISTANT:
            return False
        try:
            return bool(space.get_assistant(widget.target_id).published)
        except NotFoundException:
            return False

    def _view(self, space: "Space", widget: Widget) -> WidgetView:
        blockers = widget.activation_blockers(
            target_published=self._target_published(space, widget)
        )
        blockers.extend(self.get_policy().violations(widget))
        return WidgetView(widget=widget, activation_blockers=blockers)

    # --- queries ----------------------------------------------------------

    async def list_widgets(self, space_id: UUID) -> list[WidgetView]:
        space = await self.space_service.get_space(space_id)
        widgets = await self.repo.list_by_space(space_id)
        return [self._view(space, widget) for widget in widgets]

    async def get_widget(self, widget_id: UUID) -> WidgetView:
        widget = await self._owned_widget(widget_id)
        space = await self.space_service.get_space(widget.space_id)
        return self._view(space, widget)

    # --- commands ---------------------------------------------------------

    async def create_widget(
        self,
        *,
        space_id: UUID,
        target_id: UUID,
        name: str,
        language: WidgetLanguage = WidgetLanguage.AUTO,
    ) -> WidgetView:
        validate_permission(self.user, Permission.WIDGETS)
        space = await self._space_for_edit(space_id)
        # Raises NotFound when the assistant is not part of this space.
        space.get_assistant(target_id)
        widget = Widget.create(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            target_id=target_id,
            name=name,
            language=language,
            created_by_user_id=self.user.id,
        )
        widget = await self.repo.add(widget)
        return self._view(space, widget)

    async def update_widget(
        self, widget_id: UUID, changes: dict[str, Any]
    ) -> WidgetView:
        validate_permission(self.user, Permission.WIDGETS)
        widget = await self._owned_widget(widget_id)
        space = await self._space_for_edit(widget.space_id)
        widget.apply_update(changes)
        violations = self.get_policy().violations(widget)
        if violations:
            raise BadRequestException(
                "Widget configuration violates tenant policy: " + ", ".join(violations)
            )
        widget = await self.repo.update(widget)
        return self._view(space, widget)

    async def activate_widget(self, widget_id: UUID) -> WidgetView:
        validate_permission(self.user, Permission.ADMIN)
        widget = await self._owned_widget(widget_id)
        space = await self.space_service.get_space(widget.space_id)
        view = self._view(space, widget)
        blockers = list(view.activation_blockers)
        policy = self.get_policy()
        active = await self.repo.count_active(self.user.tenant_id)
        if widget.status != WidgetStatus.ACTIVE and active >= policy.max_active_widgets:
            blockers.append("max_active_widgets_reached")
        if blockers:
            raise BadRequestException(
                "Widget cannot be activated: " + ", ".join(blockers)
            )
        widget.activate(by=self.user.id)
        widget = await self.repo.update(widget)
        return self._view(space, widget)

    async def pause_widget(self, widget_id: UUID) -> WidgetView:
        widget = await self._owned_widget(widget_id)
        # Pausing is the kill switch: any space editor with the widgets
        # permission may stop a widget, not only tenant admins.
        if Permission.ADMIN in self.user.permissions:
            space = await self.space_service.get_space(widget.space_id)
        else:
            validate_permission(self.user, Permission.WIDGETS)
            space = await self._space_for_edit(widget.space_id)
        widget.pause()
        widget = await self.repo.update(widget)
        return self._view(space, widget)

    async def archive_widget(self, widget_id: UUID) -> WidgetView:
        validate_permission(self.user, Permission.ADMIN)
        widget = await self._owned_widget(widget_id)
        space = await self.space_service.get_space(widget.space_id)
        widget.archive()
        widget = await self.repo.update(widget)
        return self._view(space, widget)
