# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.roles.permissions import Permission, validate_permission
from eneo.users.user import UserInDB
from eneo.widgets.domain.exceptions import WidgetTemplateInUseError
from eneo.widgets.domain.widget import Widget, WidgetLanguage, WidgetStatus
from eneo.widgets.domain.widget_repo import WidgetRepo
from eneo.widgets.domain.widget_template import WidgetTemplate
from eneo.widgets.domain.widget_template_repo import WidgetTemplateRepo


@dataclass(frozen=True)
class TemplateUpdateResult:
    template: WidgetTemplate
    # Linked widgets whose locked groups changed with this save.
    synced_widgets: list[Widget]


class WidgetTemplateService:
    """Admins own the templates; editors with the widgets permission read them.

    A template save is written onto every widget that follows it, in the same
    transaction, so a widget row is always what its visitors see and the
    template is never "ahead" of its widgets.
    """

    def __init__(
        self, user: UserInDB, repo: WidgetTemplateRepo, widget_repo: WidgetRepo
    ) -> None:
        self.user = user
        self.repo = repo
        self.widget_repo = widget_repo

    async def _owned(self, template_id: UUID) -> WidgetTemplate:
        template = await self.repo.get(template_id)
        if template is None or template.tenant_id != self.user.tenant_id:
            raise NotFoundException("Widget template not found.")
        return template

    def _require_reader(self) -> None:
        if Permission.ADMIN not in self.user.permissions:
            validate_permission(self.user, Permission.WIDGETS)

    async def list_templates(self) -> list[WidgetTemplate]:
        self._require_reader()
        return await self.repo.list_by_tenant(self.user.tenant_id)

    async def linked_widget_counts(self) -> dict[UUID, int]:
        """How many widgets follow each of the organisation's templates."""
        self._require_reader()
        return await self.widget_repo.count_by_template(self.user.tenant_id)

    async def get_template(self, template_id: UUID) -> WidgetTemplate:
        self._require_reader()
        return await self._owned(template_id)

    async def create_template(
        self,
        *,
        name: str,
        language: WidgetLanguage = WidgetLanguage.AUTO,
        is_default: bool = False,
    ) -> WidgetTemplate:
        validate_permission(self.user, Permission.ADMIN)
        template = WidgetTemplate.create(
            tenant_id=self.user.tenant_id,
            name=name,
            language=language,
            created_by_user_id=self.user.id,
        )
        if is_default:
            await self.repo.clear_default(self.user.tenant_id)
            template.is_default = True
        return await self.repo.add(template)

    async def update_template(
        self, template_id: UUID, changes: dict[str, Any]
    ) -> TemplateUpdateResult:
        validate_permission(self.user, Permission.ADMIN)
        template = await self._owned(template_id)
        try:
            template.apply_update(changes)
        except ValidationError as exc:
            raise BadRequestException(str(exc)) from exc
        violations = template.lock_violations()
        if violations:
            raise BadRequestException(
                "Template locks cannot be enforced: " + ", ".join(violations)
            )
        if changes.get("is_default") is True:
            await self.repo.clear_default(self.user.tenant_id)
        template = await self.repo.update(template)
        return TemplateUpdateResult(
            template=template, synced_widgets=await self._sync_linked(template)
        )

    async def _sync_linked(self, template: WidgetTemplate) -> list[Widget]:
        assert template.id is not None
        synced: list[Widget] = []
        for widget in await self.widget_repo.list_by_template(template.id):
            # Archived widgets are frozen history; nothing follows them.
            if widget.status == WidgetStatus.ARCHIVED:
                continue
            if template.project_onto(widget, template.locked_groups):
                synced.append(await self.widget_repo.update(widget))
        return synced

    async def delete_template(self, template_id: UUID) -> WidgetTemplate:
        validate_permission(self.user, Permission.ADMIN)
        template = await self._owned(template_id)
        assert template.id is not None
        linked = len(await self.widget_repo.list_by_template(template.id))
        if linked:
            raise WidgetTemplateInUseError(linked)
        await self.repo.delete(template.id)
        return template
