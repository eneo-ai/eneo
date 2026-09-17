# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Any
from uuid import UUID

from pydantic import ValidationError

from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.roles.permissions import Permission, validate_permission
from eneo.users.user import UserInDB
from eneo.widgets.domain.widget import WidgetLanguage
from eneo.widgets.domain.widget_template import WidgetTemplate
from eneo.widgets.domain.widget_template_repo import WidgetTemplateRepo


class WidgetTemplateService:
    """Admins own the templates; editors with the widgets permission read them."""

    def __init__(self, user: UserInDB, repo: WidgetTemplateRepo) -> None:
        self.user = user
        self.repo = repo

    async def _owned(self, template_id: UUID) -> WidgetTemplate:
        template = await self.repo.get(template_id)
        if template is None or template.tenant_id != self.user.tenant_id:
            raise NotFoundException("Widget template not found.")
        return template

    async def list_templates(self) -> list[WidgetTemplate]:
        if Permission.ADMIN not in self.user.permissions:
            validate_permission(self.user, Permission.WIDGETS)
        return await self.repo.list_by_tenant(self.user.tenant_id)

    async def get_template(self, template_id: UUID) -> WidgetTemplate:
        if Permission.ADMIN not in self.user.permissions:
            validate_permission(self.user, Permission.WIDGETS)
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
    ) -> WidgetTemplate:
        validate_permission(self.user, Permission.ADMIN)
        template = await self._owned(template_id)
        try:
            template.apply_update(changes)
        except ValidationError as exc:
            raise BadRequestException(str(exc)) from exc
        if changes.get("is_default") is True:
            await self.repo.clear_default(self.user.tenant_id)
        return await self.repo.update(template)

    async def delete_template(self, template_id: UUID) -> WidgetTemplate:
        validate_permission(self.user, Permission.ADMIN)
        template = await self._owned(template_id)
        assert template.id is not None
        await self.repo.delete(template.id)
        return template
