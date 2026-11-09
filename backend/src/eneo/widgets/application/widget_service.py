# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from pydantic import ValidationError

from eneo.icons.icon_repo import IconRepository
from eneo.main.exceptions import (
    BadRequestException,
    KnowledgeModelUnavailableException,
    ModelNotAvailableException,
    NoModelSelectedException,
    NotFoundException,
    SecurityClassificationMismatchException,
    UnauthorizedException,
)
from eneo.mcp_servers.application.capability_resolver import general_servers_for_space
from eneo.roles.permissions import Permission, validate_permission
from eneo.users.user import UserInDB
from eneo.widgets.application.visitor_token_service import VisitorTokenService
from eneo.widgets.domain.exceptions import (
    WidgetAdminRequiredError,
    WidgetExternalToolsUnacknowledgedError,
    WidgetFieldLockedError,
    WidgetPolicyViolationError,
    WidgetPreviewUnavailableError,
    WidgetRevisionConflictError,
    WidgetServingBlockedError,
    WidgetTemplateNotPublishedError,
)
from eneo.widgets.domain.widget import (
    GOVERNED_FIELDS,
    LIFECYCLE_FIELDS,
    BotProtection,
    Widget,
    WidgetLanguage,
    WidgetStatus,
    WidgetTargetType,
    WidgetUpdate,
    validation_messages,
)
from eneo.widgets.domain.widget_policy import WidgetPolicy
from eneo.widgets.domain.widget_repo import WidgetRepo
from eneo.widgets.domain.widget_template import ALL_LOCK_GROUPS, WidgetTemplate
from eneo.widgets.domain.widget_template_repo import WidgetTemplateRepo

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.assistants.assistant import Assistant
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.spaces.space_service import SpaceService
    from eneo.tenants.tenant_service import TenantService


@dataclass(frozen=True)
class ExternalToolServer:
    """An MCP server outside Eneo that a visitor turn of the target reaches,
    with the tools it exposes. What the admin acknowledges at activation."""

    id: UUID
    name: str
    tools: list[str]

    def public(self) -> dict[str, Any]:
        return {"id": str(self.id), "name": self.name, "tools": list(self.tools)}


@dataclass(frozen=True)
class WidgetView:
    widget: Widget
    activation_blockers: list[str]
    # The target's MCP servers outside Eneo, and whether the admin's stored
    # acknowledgement covers exactly that set (true when there are none).
    external_tools: list[ExternalToolServer]
    external_tools_acknowledged: bool
    # The template the widget follows, when any; carries the lock groups the
    # editor must show as read-only.
    template: Optional[WidgetTemplate] = None
    # The widget before a change, read under the same row lock as the change,
    # so an audit entry's "old" is what the change replaced.
    previous: Optional[Widget] = None


@dataclass(frozen=True)
class WidgetOverviewDetails:
    """What the admin overview shows of a widget besides its row and usage."""

    activation_blockers: list[str]
    external_tools: list[ExternalToolServer]
    external_tools_acknowledged: bool


class WidgetService:
    def __init__(
        self,
        user: UserInDB,
        repo: WidgetRepo,
        template_repo: WidgetTemplateRepo,
        space_service: "SpaceService",
        actor_manager: "ActorManager",
        tenant_service: "TenantService",
        icon_repo: IconRepository,
        space_repo: "SpaceRepository",
        token_service: Optional[VisitorTokenService] = None,
    ) -> None:
        self.user = user
        self.repo = repo
        self.template_repo = template_repo
        self.space_service = space_service
        self.actor_manager = actor_manager
        self.tenant_service = tenant_service
        self.icon_repo = icon_repo
        self.space_repo = space_repo
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
        # Merge into the row as it is now, held until commit: the policy
        # loaded with the user may predate another administrator's save.
        current = await self.tenant_service.lock_widget_policy(self.user.tenant_id)
        before = WidgetPolicy.from_tenant(current)
        merged = dict(current)
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

    async def _space_for_read(self, space_id: UUID) -> "Space":
        """Widget configuration is read by those who may change it there.

        The tenant-wide ``widgets`` permission alone does not open another
        space's origins, limits and usage to a member who only views it;
        tenant admins read every space they can see.
        """
        if Permission.ADMIN in self.user.permissions:
            return await self.space_service.get_space(space_id)
        return await self._space_for_edit(space_id)

    async def _space_as_admin(self, space_id: UUID) -> "Space":
        # Tenant admins run the lifecycle from the admin page, also for widgets
        # in spaces they are not members of, so no space-level read check.
        return await self.space_service.repo.one(space_id)

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
    def _target(space: "Space", widget: Widget) -> Optional["Assistant"]:
        if widget.target_type != WidgetTargetType.ASSISTANT:
            return None
        try:
            return space.get_assistant(widget.target_id)
        except NotFoundException:
            return None

    @staticmethod
    def _can_answer(space: "Space", target: "Assistant") -> bool:
        """The check every question to the assistant has to pass."""
        try:
            space.can_ask_assistant(assistant=target)
        except (
            KnowledgeModelUnavailableException,
            ModelNotAvailableException,
            NoModelSelectedException,
            SecurityClassificationMismatchException,
        ):
            return False
        return True

    @staticmethod
    def _external_tools(
        space: "Space", target: Optional["Assistant"]
    ) -> list[ExternalToolServer]:
        """The target's MCP servers outside Eneo that a visitor turn reaches.

        The general-purpose servers attached to the assistant within the
        space's security classification, as AssistantService hands them to a
        turn. Capability providers (web search) are left out: the tenant
        chose them, they only read, and a visitor never gets any other
        capability. Eneo's own loopback servers are not external.
        """
        if target is None:
            return []
        attached: Sequence["MCPServer"] = target.mcp_servers
        servers = general_servers_for_space(attached, space.security_classification)
        external: list[ExternalToolServer] = []
        for server in servers:
            if server.is_internal or not server.is_enabled:
                continue
            tools = (
                sorted(
                    tool.title or tool.name for tool in server.tools if tool.is_enabled
                )
                if server.tools_loaded
                else []
            )
            external.append(ExternalToolServer(server.id, server.name, tools))
        return sorted(external, key=lambda server: server.name.casefold())

    def _activation_blockers(
        self,
        space: "Space",
        widget: Widget,
        *,
        external: Optional[list[ExternalToolServer]] = None,
    ) -> list[str]:
        target = self._target(space, widget)
        if external is None:
            external = self._external_tools(space, target)
        blockers = widget.activation_blockers(
            target_published=target is not None and bool(target.published)
        )
        if target is not None and not self._can_answer(space, target):
            blockers.append("target_cannot_answer")
        if external and not self.get_policy().allow_external_tools:
            blockers.append("external_tools_not_allowed")
        if widget.is_serving and not widget.external_tools_acknowledged(
            server.id for server in external
        ):
            # Live, but the assistant's external servers are not the ones the
            # admin acknowledged: pausing and activating again asks for a
            # new acknowledgement.
            blockers.append("external_tools_changed_since_activation")
        # Widget visitors are viewers. Organization spaces grant viewers no
        # assistant read permission, so a widget there could never answer.
        if space.is_organization():
            blockers.append("organization_space_unsupported")
        # A personal space belongs to one account, and an anonymous widget on a
        # public website must not depend on it: nothing governs the assistant
        # when the person leaves. Personal assistants are meant to be reached
        # through a widget where the visitor signs in and gets their own
        # assistant, a separate feature; until it exists, drafts stay drafts.
        if space.is_personal():
            blockers.append("personal_space_unsupported")
        return blockers

    def _view(
        self,
        space: "Space",
        widget: Widget,
        template: Optional[WidgetTemplate] = None,
        *,
        previous: Optional[Widget] = None,
    ) -> WidgetView:
        external = self._external_tools(space, self._target(space, widget))
        blockers = self._activation_blockers(space, widget, external=external)
        blockers.extend(self.get_policy().violations(widget))
        return WidgetView(
            widget=widget,
            activation_blockers=blockers,
            template=template,
            external_tools=external,
            external_tools_acknowledged=widget.external_tools_acknowledged(
                server.id for server in external
            ),
            previous=previous,
        )

    async def _template_of(self, widget: Widget) -> Optional[WidgetTemplate]:
        if widget.template_id is None:
            return None
        return await self.template_repo.get(widget.template_id)

    async def _view_with_template(
        self, space: "Space", widget: Widget, *, previous: Optional[Widget] = None
    ) -> WidgetView:
        return self._view(
            space, widget, await self._template_of(widget), previous=previous
        )

    # --- queries ----------------------------------------------------------

    async def list_widgets(self, space_id: UUID) -> list[WidgetView]:
        self._require_reader()
        space = await self._space_for_read(space_id)
        widgets = await self.repo.list_by_space(space_id)
        templates = {
            template.id: template
            for template in await self.template_repo.list_by_tenant(self.user.tenant_id)
        }
        return [
            self._view(space, widget, templates.get(widget.template_id))
            for widget in widgets
        ]

    async def get_widget(self, widget_id: UUID) -> WidgetView:
        self._require_reader()
        widget = await self._owned_widget(widget_id)
        space = await self._space_for_read(widget.space_id)
        return await self._view_with_template(space, widget)

    async def overview_details_of(
        self, widgets: Sequence[Widget]
    ) -> dict[Optional[UUID], WidgetOverviewDetails]:
        """The blockers and external tools of widgets from any space, for the
        tenant admin's overview. What the assistant can do is read from its
        space, so each space is loaded once."""
        spaces: dict[UUID, "Space"] = {}
        details: dict[Optional[UUID], WidgetOverviewDetails] = {}
        for widget in widgets:
            if widget.space_id not in spaces:
                spaces[widget.space_id] = await self._space_as_admin(widget.space_id)
            view = self._view(spaces[widget.space_id], widget)
            details[widget.id] = WidgetOverviewDetails(
                activation_blockers=view.activation_blockers,
                external_tools=view.external_tools,
                external_tools_acknowledged=view.external_tools_acknowledged,
            )
        return details

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
        if space.is_organization():
            raise BadRequestException(
                "Widgets cannot be created in the organization space."
                " Choose a shared space."
            )
        if space.is_personal():
            # See _activation_blockers: a public widget needs a space the
            # organization governs, not one account's own.
            raise BadRequestException(
                "Widgets cannot be created in a personal space. Choose a shared space."
            )
        # The space row first, then the assistant: the order a transfer or a
        # space deletion takes, so neither side holds the assistant while it
        # waits for the space. Both are held until commit, so a move or a
        # deletion that follows sees the new widget and refuses or archives.
        await self.space_repo.lock(space_id)
        space = await self._space_for_edit(space_id)
        # Raises NotFound when the assistant is not part of this space.
        space.get_assistant(target_id)
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
        return self._view(space, widget, template)

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
        # Row lock first, icons after (IconRepository.lock_for_change): an
        # update and a template publication swapping avatars then queue on
        # the widget row instead of deadlocking on the icons.
        widget = await self._owned_widget(widget_id, for_update=True)
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
        # Template before widget, the order a publication takes them in: an
        # existing follower reapplying its release while that release is
        # being published then queues on the template instead of deadlocking
        # against the publication's lock on the follower rows.
        template = await self._template_to_follow(template_id)
        widget, space = await self._widget_for_change(widget_id, revision)
        before = widget.model_copy(deep=True)
        self._link(widget, template)
        self._hold_to_rules(before, widget)
        widget = await self.repo.update(widget)
        # The template's avatar replaced the widget's own; the old one goes
        # unless something else still shows it.
        await self.icon_repo.release_replaced(
            before.persona.avatar_icon_id, widget.persona.avatar_icon_id
        )
        return self._view(space, widget, template)

    def _require_admin_while_active(
        self, widget: Widget, changed: Iterable[str]
    ) -> None:
        """An active widget's governed settings are what the tenant admin
        reviewed at activation (GOVERNED_FIELDS, and the template whose locks
        an admin set). An editor changes them by pausing first, which also
        makes the next activation a new review; an admin changes them live.
        """
        fields = sorted(changed)
        if not fields or not widget.is_serving:
            return
        if Permission.ADMIN in self.user.permissions:
            return
        raise WidgetAdminRequiredError(fields)

    async def detach_template(self, widget_id: UUID, *, revision: int) -> WidgetView:
        """Stop following the template; the widget keeps its current values.

        The template's locks only hold while the widget follows it, so on an
        active widget detaching is an admin's decision (_require_admin_while_active).
        """
        validate_permission(self.user, Permission.WIDGETS)
        widget, space = await self._widget_for_change(widget_id, revision)
        self._require_admin_while_active(widget, ["template"])
        before = widget.model_copy(deep=True)
        widget.template_id = None
        widget = await self.repo.update(widget)
        return await self._view_with_template(space, widget, previous=before)

    async def update_widget(self, widget_id: UUID, update: WidgetUpdate) -> WidgetView:
        validate_permission(self.user, Permission.WIDGETS)
        changes = update.changes()
        widget, space = await self._widget_for_change(widget_id, update.revision)
        template = await self._template_of(widget)
        if template is not None and template.published is not None:
            locked = template.published.locked_changes(widget, changes)
            if locked:
                raise WidgetFieldLockedError(locked)
        self._require_admin_while_active(
            widget,
            (
                name
                for name, value in changes.items()
                if name in GOVERNED_FIELDS and value != getattr(widget, name)
            ),
        )
        before = widget.model_copy(deep=True)
        widget.apply_update(changes)
        self._hold_to_rules(before, widget)
        # Only the editor's own uploads can become the avatar; the id is public.
        await self.icon_repo.ensure_attachable(
            before.persona.avatar_icon_id,
            widget.persona.avatar_icon_id,
            tenant_id=self.user.tenant_id,
            user_id=self.user.id,
        )
        widget = await self.repo.update(widget)
        await self.icon_repo.release_replaced(
            before.persona.avatar_icon_id, widget.persona.avatar_icon_id
        )
        return self._view(space, widget, template, previous=before)

    async def activate_widget(
        self, widget_id: UUID, *, external_tools_acknowledged: bool = False
    ) -> WidgetView:
        """Put the widget online. Tenant admins only.

        When the assistant reaches MCP servers outside Eneo, the admin must
        acknowledge that anonymous visitors can make it call their tools
        (``external_tools_acknowledged``), unless the stored acknowledgement
        already covers exactly those servers. The acknowledgement is recorded
        with the server ids, so a changed set asks again.
        """
        validate_permission(self.user, Permission.ADMIN)
        widget = await self._owned_widget(widget_id)
        space = await self._space_as_admin(widget.space_id)
        violations = self.get_policy().violations(widget)
        if violations:
            raise WidgetPolicyViolationError(violations)
        external = self._external_tools(space, self._target(space, widget))
        blockers = self._activation_blockers(space, widget, external=external)
        if blockers:
            raise WidgetServingBlockedError(blockers)
        server_ids = [server.id for server in external]
        if not widget.external_tools_acknowledged(server_ids):
            if not external_tools_acknowledged:
                raise WidgetExternalToolsUnacknowledgedError(
                    [server.public() for server in external]
                )
            widget.acknowledge_external_tools(server_ids, by=self.user.id)
        elif not external:
            widget.external_tools_acknowledgement = None
        widget.activate(by=self.user.id)
        widget = await self.repo.update(widget)
        return await self._view_with_template(space, widget)

    async def preview_token(self, widget_id: UUID) -> tuple[str, int]:
        """A visitor token for the editor's live preview.

        Works for draft widgets, so editors can see the embed page before an
        admin activates it, and for active ones. A paused widget is not
        previewed: the pause is the kill switch and nothing admits the embed
        page behind it. Each call is a fresh pseudonymous visitor; nothing
        about the editor is put in the token.
        """
        validate_permission(self.user, Permission.WIDGETS)
        widget = await self._owned_widget(widget_id)
        await self._space_for_edit(widget.space_id)
        if widget.status == WidgetStatus.ARCHIVED:
            raise BadRequestException("Archived widgets cannot be previewed.")
        if widget.status == WidgetStatus.PAUSED:
            raise WidgetPreviewUnavailableError()
        return self.token_service.mint(widget, uuid4(), preview=True)

    async def pause_widget(self, widget_id: UUID) -> WidgetView:
        # Read locked: the write below skips the revision check, so the
        # status and generation it writes must be the row's current ones.
        widget = await self._owned_widget(widget_id, for_update=True)
        # Pausing is the kill switch: any space editor with the widgets
        # permission may stop a widget, not only tenant admins.
        if Permission.ADMIN in self.user.permissions:
            space = await self._space_as_admin(widget.space_id)
        else:
            validate_permission(self.user, Permission.WIDGETS)
            space = await self._space_for_edit(widget.space_id)
        widget.pause()
        widget = await self.repo.update(
            widget, check_revision=False, only=LIFECYCLE_FIELDS
        )
        return await self._view_with_template(space, widget)

    async def archive_widget(self, widget_id: UUID) -> WidgetView:
        validate_permission(self.user, Permission.ADMIN)
        widget = await self._owned_widget(widget_id, for_update=True)
        space = await self._space_as_admin(widget.space_id)
        widget.archive()
        widget = await self.repo.update(
            widget, check_revision=False, only=LIFECYCLE_FIELDS
        )
        return await self._view_with_template(space, widget)
