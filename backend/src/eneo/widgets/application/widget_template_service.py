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
from eneo.widgets.domain.widget import (
    Widget,
    WidgetLanguage,
    WidgetStatus,
    validation_messages,
)
from eneo.widgets.domain.widget_repo import WidgetRepo
from eneo.widgets.domain.widget_template import TemplateLockGroup, WidgetTemplate
from eneo.widgets.domain.widget_template_repo import WidgetTemplateRepo


@dataclass(frozen=True)
class TemplatePublishResult:
    template: WidgetTemplate
    # Followers whose locked groups changed with this publication.
    synced_widgets: list[Widget]


class WidgetTemplateService:
    """Admins own the templates; editors with the widgets permission read them.

    Saving a template only changes its draft. Publishing turns the draft into
    the release followers are held to and writes the locked groups onto every
    follower in the same transaction, so a widget row is always what its
    visitors see and a release is never "ahead" of its widgets.
    """

    def __init__(
        self, user: UserInDB, repo: WidgetTemplateRepo, widget_repo: WidgetRepo
    ) -> None:
        self.user = user
        self.repo = repo
        self.widget_repo = widget_repo

    async def _owned(
        self, template_id: UUID, *, for_update: bool = False
    ) -> WidgetTemplate:
        template = await self.repo.get(template_id, for_update=for_update)
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
    ) -> WidgetTemplate:
        """Edit the draft. Followers are untouched until the next publication."""
        validate_permission(self.user, Permission.ADMIN)
        # Locked: the write carries the release too, and a publication that
        # commits in between must not be written back over.
        template = await self._owned(template_id, for_update=True)
        try:
            template.apply_update(changes)
        except ValidationError as exc:
            raise BadRequestException(
                f"Invalid template: {validation_messages(exc)}"
            ) from exc
        self._assert_locks_enforceable(template)
        if changes.get("is_default") is True:
            await self.repo.clear_default(self.user.tenant_id)
        return await self.repo.update(template)

    async def publish_template(self, template_id: UUID) -> TemplatePublishResult:
        validate_permission(self.user, Permission.ADMIN)
        # The template lock comes before the followers' (taken while syncing)
        # and before any widget that links meanwhile.
        template = await self._owned(template_id, for_update=True)
        self._assert_locks_enforceable(template)
        previous_locks: set[TemplateLockGroup] = (
            set(template.published.locked_groups) if template.published else set()
        )
        template.publish(by=self.user.id)
        template = await self.repo.update(template)
        assert template.published is not None
        # New locks with unchanged values still change what the editor may
        # touch; bump the followers so open editors reload and see them.
        locks_changed = set(template.published.locked_groups) != previous_locks
        return TemplatePublishResult(
            template=template,
            synced_widgets=await self._sync_followers(template, force=locks_changed),
        )

    @staticmethod
    def _assert_locks_enforceable(template: WidgetTemplate) -> None:
        violations = template.lock_violations()
        if violations:
            raise BadRequestException(
                "Template locks cannot be enforced: " + ", ".join(violations)
            )

    async def _sync_followers(
        self, template: WidgetTemplate, *, force: bool = False
    ) -> list[Widget]:
        assert template.id is not None and template.published is not None
        release = template.published
        synced: list[Widget] = []
        for widget in await self.widget_repo.list_by_template(template.id):
            # Archived widgets are frozen history; nothing follows them.
            if widget.status == WidgetStatus.ARCHIVED:
                continue
            if release.project_onto(widget, release.locked_groups) or force:
                synced.append(await self.widget_repo.update(widget))
        return synced

    async def delete_template(self, template_id: UUID) -> WidgetTemplate:
        validate_permission(self.user, Permission.ADMIN)
        template = await self._owned(template_id, for_update=True)
        assert template.id is not None
        # Archived widgets never block deletion; the foreign key clears
        # their link when the template goes, so only the audit log records it.
        linked = len(await self.widget_repo.list_by_template(template.id))
        if linked:
            raise WidgetTemplateInUseError(linked)
        await self.repo.delete(template.id)
        return template
