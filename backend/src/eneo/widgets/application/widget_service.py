# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from pydantic import ValidationError

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission, validate_permission
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.oversight_models import (
    AdminSpaceKnowledgeSource,
    AdminSpaceViewerMembership,
)
from eneo.spaces.oversight.oversight_repo import (
    AssistantConfig,
    SpaceOversightRepo,
    SpaceSummaryRow,
)
from eneo.spaces.oversight.oversight_service import viewer_membership_of
from eneo.users.user import UserInDB
from eneo.widgets.application.visitor_token_service import VisitorTokenService
from eneo.widgets.domain.exceptions import (
    WidgetFieldLockedError,
    WidgetPolicyViolationError,
    WidgetRevisionConflictError,
    WidgetServingBlockedError,
    WidgetTemplateNotPublishedError,
)
from eneo.widgets.domain.widget import (
    ACTIVATION_REVIEW_FIELDS,
    LIFECYCLE_FIELDS,
    BotProtection,
    Widget,
    WidgetLanguage,
    WidgetStatus,
    WidgetTargetType,
    validation_messages,
)
from eneo.widgets.domain.widget_policy import WidgetPolicy
from eneo.widgets.domain.widget_repo import WidgetRepo
from eneo.widgets.domain.widget_template import ALL_LOCK_GROUPS, WidgetTemplate
from eneo.widgets.domain.widget_template_repo import WidgetTemplateRepo

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.spaces.space import Space
    from eneo.spaces.space_service import SpaceService
    from eneo.tenants.tenant_service import TenantService


@dataclass(frozen=True)
class ActivationRequestRef:
    requested_at: datetime
    requested_by_user_id: Optional[UUID]

    @classmethod
    def pending_on(cls, widget: Widget) -> Optional["ActivationRequestRef"]:
        if widget.activation_requested_at is None:
            return None
        return cls(
            requested_at=widget.activation_requested_at,
            requested_by_user_id=widget.activation_requested_by_user_id,
        )


@dataclass(frozen=True)
class WidgetView:
    widget: Widget
    activation_blockers: list[str]
    # The template the widget follows, when any; carries the lock groups the
    # editor must show as read-only.
    template: Optional[WidgetTemplate] = None
    # The pending request an activate or send-back settled, for its audit
    # entry: the command clears it from the widget.
    settled_request: Optional[ActivationRequestRef] = None


@dataclass(frozen=True)
class WidgetReviewFacts:
    view: WidgetView
    space: SpaceSummaryRow
    # None for a personal space's assistant or a deleted one.
    target: Optional[AssistantConfig]
    knowledge: list[AdminSpaceKnowledgeSource]
    viewer_role: Optional[SpaceRoleValue]
    # Shared spaces only: the others cannot be joined through oversight.
    viewer_membership: Optional[AdminSpaceViewerMembership]


class WidgetService:
    def __init__(
        self,
        user: UserInDB,
        repo: WidgetRepo,
        template_repo: WidgetTemplateRepo,
        space_service: "SpaceService",
        actor_manager: "ActorManager",
        tenant_service: "TenantService",
        oversight_repo: SpaceOversightRepo,
        token_service: Optional[VisitorTokenService] = None,
    ) -> None:
        self.user = user
        self.repo = repo
        self.template_repo = template_repo
        self.space_service = space_service
        self.actor_manager = actor_manager
        self.tenant_service = tenant_service
        self.oversight_repo = oversight_repo
        self.token_service = token_service or VisitorTokenService()

    # --- policy -----------------------------------------------------------

    def get_policy(self) -> WidgetPolicy:
        return WidgetPolicy.from_tenant(self.user.tenant.widget_policy)

    def read_policy(self) -> WidgetPolicy:
        """Read-only for everyone who manages widgets, so the editor can hold
        its fields to the same limits the server does; only admins change it."""
        self._require_reader()
        return self.get_policy()

    async def update_policy(self, updates: dict[str, Any]) -> WidgetPolicy:
        validate_permission(self.user, Permission.ADMIN)
        before = self.get_policy()
        merged = dict(self.user.tenant.widget_policy or {})
        merged.update(updates)
        # Validate the merged document before persisting so a partial update
        # can never leave the tenant with an inconsistent window.
        try:
            policy = WidgetPolicy.from_tenant(merged)
        except ValidationError as exc:
            raise BadRequestException(
                f"Invalid widget policy: {validation_messages(exc)}"
            ) from exc
        tenant = await self.tenant_service.update_widget_policy(
            self.user.tenant_id, policy.model_dump(mode="json")
        )
        if before.allow_bot_protection_none and not policy.allow_bot_protection_none:
            # Visitors admitted without a challenge must solve one now: their
            # tokens stop validating and the embed page's cached config with it.
            await self.repo.revoke_tokens(
                self.user.tenant_id, bot_protection=BotProtection.NONE
            )
        return WidgetPolicy.from_tenant(tenant.widget_policy)

    # --- helpers ----------------------------------------------------------

    def _require_reader(self) -> None:
        """Widget configuration (origins, limits, privacy) is for the people
        who manage widgets, not for every space member."""
        if Permission.ADMIN not in self.user.permissions:
            validate_permission(self.user, Permission.WIDGETS)

    async def _space_for_edit(self, space_id: UUID) -> "Space":
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to manage widgets in this space."
            )
        return space

    async def _owned_widget(
        self, widget_id: UUID, *, for_update: bool = False
    ) -> Widget:
        widget = await self.repo.get(widget_id, for_update=for_update)
        if widget is None or widget.tenant_id != self.user.tenant_id:
            raise NotFoundException("Widget not found.")
        return widget

    async def _template_to_follow(self, template_id: UUID) -> WidgetTemplate:
        """The template a widget is about to follow, locked for the rest of
        the transaction so a publication cannot slip in between reading the
        release and persisting the widget that copies it."""
        template = await self.template_repo.get(template_id, for_update=True)
        if template is None or template.tenant_id != self.user.tenant_id:
            raise NotFoundException("Widget template not found.")
        return template

    @staticmethod
    def _target_published(space: "Space", widget: Widget) -> bool:
        if widget.target_type != WidgetTargetType.ASSISTANT:
            return False
        try:
            return bool(space.get_assistant(widget.target_id).published)
        except NotFoundException:
            return False

    def _view(
        self,
        widget: Widget,
        *,
        target_published: bool,
        template: Optional[WidgetTemplate] = None,
    ) -> WidgetView:
        blockers = widget.activation_blockers(target_published=target_published)
        blockers.extend(self.get_policy().violations(widget))
        return WidgetView(
            widget=widget, activation_blockers=blockers, template=template
        )

    async def _template_of(self, widget: Widget) -> Optional[WidgetTemplate]:
        if widget.template_id is None:
            return None
        return await self.template_repo.get(widget.template_id)

    async def _view_with_template(
        self, widget: Widget, *, target_published: bool
    ) -> WidgetView:
        return self._view(
            widget,
            target_published=target_published,
            template=await self._template_of(widget),
        )

    async def _member_view(self, space: "Space", widget: Widget) -> WidgetView:
        return await self._view_with_template(
            widget, target_published=self._target_published(space, widget)
        )

    # --- queries ----------------------------------------------------------

    async def list_widgets(self, space_id: UUID) -> list[WidgetView]:
        self._require_reader()
        space = await self.space_service.get_space(space_id)
        widgets = await self.repo.list_by_space(space_id)
        templates = {
            template.id: template
            for template in await self.template_repo.list_by_tenant(self.user.tenant_id)
        }
        return [
            self._view(
                widget,
                target_published=self._target_published(space, widget),
                template=templates.get(widget.template_id),
            )
            for widget in widgets
        ]

    async def get_widget(self, widget_id: UUID) -> WidgetView:
        self._require_reader()
        widget = await self._owned_widget(widget_id)
        space = await self.space_service.get_space(widget.space_id)
        return await self._member_view(space, widget)

    # --- commands ---------------------------------------------------------

    async def create_widget(
        self,
        *,
        space_id: UUID,
        target_id: UUID,
        name: str,
        language: WidgetLanguage = WidgetLanguage.AUTO,
        template_id: Optional[UUID] = None,
    ) -> WidgetView:
        validate_permission(self.user, Permission.WIDGETS)
        space = await self._space_for_edit(space_id)
        # Raises NotFound when the assistant is not part of this space.
        space.get_assistant(target_id)
        # Held until commit: moving or deleting the assistant waits for the
        # new widget, so it sees it and refuses the move or archives it.
        if await self.repo.lock_target_space(target_id) != space_id:
            raise NotFoundException("Assistant not found in this space.")
        template = (
            await self._template_to_follow(template_id)
            if template_id is not None
            else None
        )
        widget = Widget.create(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            target_id=target_id,
            name=name,
            language=template.language if template else language,
            created_by_user_id=self.user.id,
        )
        if template is not None:
            self._link(widget, template)
        widget = await self.repo.add(widget)
        return self._view(
            widget,
            target_published=self._target_published(space, widget),
            template=template,
        )

    @staticmethod
    def _link(widget: Widget, template: WidgetTemplate) -> None:
        """Make the widget follow the template's published release.

        Every templated group is copied now; from here on the release's
        locked groups are kept in step with each publication and the editor
        cannot change them. Suggested questions stay the widget's own.
        """
        if template.published is None:
            raise WidgetTemplateNotPublishedError()
        widget.template_id = template.id
        template.published.project_onto(widget, ALL_LOCK_GROUPS)

    def _hold_to_rules(self, before: Widget, after: Widget) -> None:
        """Refuse an edit that sets a value outside the tenant policy, or that
        would leave an active widget unable to serve (its AI disclosure or
        its origins emptied)."""
        violations = self.get_policy().violations_introduced(before, after)
        if violations:
            raise WidgetPolicyViolationError(violations)
        if after.is_serving:
            blockers = after.blockers_introduced_since(before)
            if blockers:
                raise WidgetServingBlockedError(blockers)

    async def _widget_for_change(
        self, widget_id: UUID, revision: int
    ) -> tuple[Widget, "Space"]:
        widget = await self._owned_widget(widget_id)
        space = await self._space_for_edit(widget.space_id)
        if widget.revision != revision:
            raise WidgetRevisionConflictError()
        if widget.status == WidgetStatus.ARCHIVED:
            raise BadRequestException("Archived widgets cannot be changed.")
        return widget, space

    async def link_template(
        self, widget_id: UUID, template_id: UUID, *, revision: int
    ) -> WidgetView:
        validate_permission(self.user, Permission.WIDGETS)
        widget, space = await self._widget_for_change(widget_id, revision)
        template = await self._template_to_follow(template_id)
        before = widget.model_copy(deep=True)
        self._link(widget, template)
        self._hold_to_rules(before, widget)
        widget = await self.repo.update(widget)
        return self._view(
            widget,
            target_published=self._target_published(space, widget),
            template=template,
        )

    async def detach_template(self, widget_id: UUID, *, revision: int) -> WidgetView:
        """Stop following the template; the widget keeps its current values."""
        validate_permission(self.user, Permission.WIDGETS)
        widget, space = await self._widget_for_change(widget_id, revision)
        widget.template_id = None
        widget = await self.repo.update(widget)
        return await self._member_view(space, widget)

    async def update_widget(
        self, widget_id: UUID, changes: dict[str, Any]
    ) -> WidgetView:
        validate_permission(self.user, Permission.WIDGETS)
        widget = await self._owned_widget(widget_id)
        space = await self._space_for_edit(widget.space_id)
        changes = dict(changes)
        revision = changes.pop("revision", None)
        if revision is None:
            raise BadRequestException("revision is required.")
        if revision != widget.revision:
            raise WidgetRevisionConflictError()
        template = await self._template_of(widget)
        if template is not None and template.published is not None:
            locked = template.published.locked_changes(widget, changes)
            if locked:
                raise WidgetFieldLockedError(locked)
        before = widget.model_copy(deep=True)
        widget.apply_update(changes)
        self._hold_to_rules(before, widget)
        widget = await self.repo.update(widget)
        return self._view(
            widget,
            target_published=self._target_published(space, widget),
            template=template,
        )

    async def activate_widget(
        self, widget_id: UUID, *, revision: Optional[int] = None
    ) -> WidgetView:
        """Activate the widget; tenant admins only, member or not.

        ``revision`` pins activation to the configuration the admin
        reviewed: an edit in between is refused, never published unseen.
        """
        validate_permission(self.user, Permission.ADMIN)
        widget = await self._owned_widget(widget_id)
        if revision is not None and widget.revision != revision:
            raise WidgetRevisionConflictError()
        violations = self.get_policy().violations(widget)
        if violations:
            raise WidgetPolicyViolationError(violations)
        target_published = await self.repo.is_target_published(widget)
        blockers = widget.activation_blockers(target_published=target_published)
        if blockers:
            raise WidgetServingBlockedError(blockers)
        settled = ActivationRequestRef.pending_on(widget)
        widget.activate(by=self.user.id)
        widget = await self.repo.update(widget)
        view = await self._view_with_template(widget, target_published=True)
        return replace(view, settled_request=settled)

    async def preview_token(self, widget_id: UUID) -> tuple[str, int, str]:
        """A visitor token for a live preview: (token, expires_in, public_id).

        Editors with the widgets permission test drafts and paused widgets
        in the widget editor, as before. A tenant admin tests from the review
        page only as a member of the space and only for a published
        assistant: answers come from the space's knowledge, which is content.
        Each call is a fresh pseudonymous visitor; nothing about the caller
        is put in the token.
        """
        widget = await self._owned_widget(widget_id)
        permissions = self.user.permissions
        role = await self.oversight_repo.effective_role(
            self.user.tenant_id,
            widget.space_id,
            user_id=self.user.id,
            group_ids=self.user.user_groups_ids,
        )
        if Permission.WIDGETS in permissions and role in (
            SpaceRoleValue.ADMIN,
            SpaceRoleValue.EDITOR,
        ):
            # The editor path, unchanged: the space's own edit check decides.
            await self._space_for_edit(widget.space_id)
        elif Permission.ADMIN in permissions and role is not None:
            if not await self.repo.is_target_published(widget):
                raise WidgetServingBlockedError(["target_not_published"])
        else:
            raise UnauthorizedException(
                "You need to be a member of the space to test the widget."
            )
        if widget.status == WidgetStatus.ARCHIVED:
            raise BadRequestException("Archived widgets cannot be previewed.")
        token, expires_in = self.token_service.mint(widget, uuid4(), preview=True)
        return token, expires_in, widget.public_id

    async def pause_widget(self, widget_id: UUID) -> WidgetView:
        # Read locked: the write below skips the revision check, so the
        # status and generation it writes must be the row's current ones.
        widget = await self._owned_widget(widget_id, for_update=True)
        # Pausing is the kill switch: any space editor with the widgets
        # permission may stop a widget, not only tenant admins.
        if Permission.ADMIN in self.user.permissions:
            target_published = await self.repo.is_target_published(widget)
        else:
            validate_permission(self.user, Permission.WIDGETS)
            space = await self._space_for_edit(widget.space_id)
            target_published = self._target_published(space, widget)
        widget.pause()
        widget = await self.repo.update(
            widget, check_revision=False, only=LIFECYCLE_FIELDS
        )
        return await self._view_with_template(widget, target_published=target_published)

    async def archive_widget(self, widget_id: UUID) -> WidgetView:
        validate_permission(self.user, Permission.ADMIN)
        widget = await self._owned_widget(widget_id, for_update=True)
        widget.archive()
        widget = await self.repo.update(
            widget, check_revision=False, only=LIFECYCLE_FIELDS
        )
        return await self._view_with_template(
            widget, target_published=await self.repo.is_target_published(widget)
        )

    # --- activation requests ------------------------------------------------

    async def _widget_to_request(self, widget_id: UUID) -> tuple[Widget, "Space"]:
        validate_permission(self.user, Permission.WIDGETS)
        # Read locked: the write skips the revision check, so the request
        # never loses to an autosave and never overwrites one.
        widget = await self._owned_widget(widget_id, for_update=True)
        space = await self._space_for_edit(widget.space_id)
        return widget, space

    async def request_activation(self, widget_id: UUID) -> tuple[WidgetView, bool]:
        """Ask a tenant admin to activate the widget. Refused while settings
        break the policy or block serving; a repeated request changes
        nothing. Returns the view and whether anything changed."""
        widget, space = await self._widget_to_request(widget_id)
        violations = self.get_policy().violations(widget)
        if violations:
            raise WidgetPolicyViolationError(violations)
        blockers = widget.activation_blockers(
            target_published=self._target_published(space, widget)
        )
        if blockers:
            raise WidgetServingBlockedError(blockers)
        changed = widget.request_activation(by=self.user.id)
        if changed:
            widget = await self.repo.update(
                widget, check_revision=False, only=ACTIVATION_REVIEW_FIELDS
            )
        return await self._member_view(space, widget), changed

    async def withdraw_activation_request(
        self, widget_id: UUID
    ) -> tuple[WidgetView, bool]:
        """Withdraw a pending request; nothing changes when none is pending."""
        widget, space = await self._widget_to_request(widget_id)
        changed = widget.withdraw_activation_request()
        if changed:
            widget = await self.repo.update(
                widget, check_revision=False, only=ACTIVATION_REVIEW_FIELDS
            )
        return await self._member_view(space, widget), changed

    async def decline_activation_request(
        self, widget_id: UUID, reason: str
    ) -> WidgetView:
        """Send a pending request back to the space's editors with what
        needs to change. Tenant admins only, member or not."""
        validate_permission(self.user, Permission.ADMIN)
        widget = await self._owned_widget(widget_id, for_update=True)
        settled = ActivationRequestRef.pending_on(widget)
        widget.decline_activation_request(by=self.user.id, reason=reason)
        widget = await self.repo.update(
            widget, check_revision=False, only=ACTIVATION_REVIEW_FIELDS
        )
        view = await self._view_with_template(
            widget, target_published=await self.repo.is_target_published(widget)
        )
        return replace(view, settled_request=settled)

    async def review_widget(self, widget_id: UUID) -> WidgetReviewFacts:
        """What a tenant admin reviews before activating, without being a
        member: the widget, its space, and the assistant it exposes with its
        instructions, knowledge and visitor tools. Never documents or
        conversations."""
        validate_permission(self.user, Permission.ADMIN)
        widget = await self._owned_widget(widget_id)
        view = await self._view_with_template(
            widget, target_published=await self.repo.is_target_published(widget)
        )
        tenant_id = self.user.tenant_id
        space = await self.oversight_repo.space_summary(tenant_id, widget.space_id)
        if space is None:
            raise NotFoundException("Widget not found.")
        target: Optional[AssistantConfig] = None
        knowledge: list[AdminSpaceKnowledgeSource] = []
        if space.kind != "personal":
            configs = await self.oversight_repo.assistant_configs(
                tenant_id, widget.space_id, assistant_ids=[widget.target_id]
            )
            if configs:
                target = configs[0]
                knowledge = await self.oversight_repo.knowledge_sources(
                    tenant_id,
                    widget.space_id,
                    source_ids=[ref.id for ref in target.assistant.knowledge],
                )
        group_ids = self.user.user_groups_ids
        viewer_role = await self.oversight_repo.effective_role(
            tenant_id, widget.space_id, user_id=self.user.id, group_ids=group_ids
        )
        viewer_membership: Optional[AdminSpaceViewerMembership] = None
        if space.kind == "shared":
            membership = await self.oversight_repo.membership(
                tenant_id, widget.space_id
            )
            viewer_membership = viewer_membership_of(
                membership, self.user.id, group_ids
            )
        return WidgetReviewFacts(
            view=view,
            space=space,
            target=target,
            knowledge=knowledge,
            viewer_role=viewer_role,
            viewer_membership=viewer_membership,
        )
