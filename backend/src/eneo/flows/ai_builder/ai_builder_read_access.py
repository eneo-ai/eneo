"""Who may use the AI Builder on a space, decided without a Request.

Two entry points share one set of rules (tenant action, API-key scope, space
role, session creator):

- ``authorize`` decides a request once, on the request's own database session
  before it has loaded anything else, and loads the Space the request works
  with.
- ``open_grant`` decides a session-bound design-time read later in the same
  operation. It never trusts what the operation already loaded: the
  operation's session keeps a Space it loaded earlier, roles included, and a
  review reads under a REPEATABLE READ snapshot that cannot see a later
  revocation. Every grant therefore reads a fresh, bounded access snapshot in
  its own short transaction: this caller's role rows for the space (group
  roles through the caller's current group memberships), the scoped key's
  resource row, and the flow's ownership row, never its content. Evidence
  reads and their audit rows stay in the operation's own snapshot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn, Protocol
from uuid import UUID

from eneo.database.database import sessionmanager
from eneo.flows.ai_builder.ai_builder_domain_models import BuilderSession
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderNotFoundException,
    AIBuilderUnauthorizedException,
)
from eneo.flows.flow_access_policy import (
    FlowAccessFilterMode,
    FlowApiAction,
    require_ai_builder_space_scope,
    require_flow_action,
)
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.spaces.space_repo import read_space_access_facts

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceActor
    from eneo.authentication.auth_dependencies import ScopeFilter
    from eneo.spaces.space import Space
    from eneo.spaces.space_service import SpaceService
    from eneo.users.user import UserInDB


@dataclass(frozen=True)
class AIBuilderAuthorization:
    space: "Space | None" = None


@dataclass(frozen=True)
class BuilderReadScope:
    """What a session-bound read may touch, taken from the persisted session
    row: never from a model or a request body."""

    tenant_id: UUID
    space_id: UUID
    flow_id: UUID | None
    session_id: UUID
    actor_user_id: UUID | None
    scope_filter: "ScopeFilter"


@dataclass(frozen=True)
class BuilderReadGrant:
    scope: BuilderReadScope
    action: FlowApiAction


@dataclass(frozen=True)
class BuilderAccessSnapshot:
    space: "SpaceAccessFacts | None"
    # The space of the session's flow while it is live; None when it is gone.
    flow_space_id: UUID | None


class AccessSnapshotReader(Protocol):
    def __call__(
        self, user: "UserInDB", *, space_id: UUID, flow_id: UUID | None
    ) -> Awaitable[BuilderAccessSnapshot]: ...


def scope_for_session(
    session: BuilderSession, scope_filter: "ScopeFilter"
) -> BuilderReadScope:
    return BuilderReadScope(
        tenant_id=session.tenant_id,
        space_id=session.space_id,
        flow_id=session.flow_id,
        session_id=session.id,
        actor_user_id=session.actor_user_id,
        scope_filter=scope_filter,
    )


async def read_access_snapshot(
    user: "UserInDB", *, space_id: UUID, flow_id: UUID | None
) -> BuilderAccessSnapshot:
    """One short READ COMMITTED transaction on its own connection, closed
    before the grant is decided. It reads plain rows, so nothing the
    operation's session holds can answer for it."""
    async with sessionmanager.session() as session, session.begin():
        space = await read_space_access_facts(session, user=user, space_id=space_id)
        if space is None or flow_id is None:
            return BuilderAccessSnapshot(space=space, flow_space_id=None)
        flow_space_id = await FlowRepository(session=session).get_space_id(
            flow_id=flow_id, tenant_id=user.tenant_id
        )
        return BuilderAccessSnapshot(space=space, flow_space_id=flow_space_id)


def ensure_flow_in_space(*, flow_space_id: UUID | None, space_id: UUID) -> None:
    if flow_space_id != space_id:
        raise AIBuilderBadRequestException(
            "Flow space does not match the AI builder session space.",
            code=AIBuilderErrorCode.FLOW_SPACE_MISMATCH,
        )


def _ensure_space_flow_edit_permission(actor: "SpaceActor") -> None:
    if not actor.can_edit_flows():
        raise AIBuilderUnauthorizedException(
            "You do not have permission to use the AI builder in this space.",
            code=AIBuilderErrorCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        )


def _ensure_session_creator(user: "UserInDB", actor_user_id: UUID | None) -> None:
    if actor_user_id != user.id:
        raise AIBuilderUnauthorizedException(
            "Only the session creator can access this AI builder session.",
            code=AIBuilderErrorCode.SESSION_CREATOR_REQUIRED,
            context={"auth_layer": "session_creator"},
        )


def _raise_scope_mismatch() -> NoReturn:
    raise AIBuilderUnauthorizedException(
        "API key space scope does not match requested AI builder resource.",
        code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
        context={"auth_layer": "api_key_scope"},
    )


class BuilderReadAccess:
    """Holds the principal and the rule owners; never a decision. Nothing is
    cached between calls."""

    def __init__(
        self,
        *,
        user: "UserInDB",
        space_service: Callable[[], "SpaceService"],
        actor_manager: "ActorManager",
        snapshot_reader: AccessSnapshotReader | None = None,
    ) -> None:
        self.user = user
        self._space_service = space_service
        self._actor_manager = actor_manager
        self.snapshot_reader = snapshot_reader

    async def authorize(
        self,
        scope_filter: "ScopeFilter",
        *,
        action: FlowApiAction,
        space_id: UUID | None = None,
        session: BuilderSession | None = None,
        require_creator: bool = False,
        filter_mode: FlowAccessFilterMode | None = None,
    ) -> AIBuilderAuthorization:
        require_flow_action(self.user, action)

        if filter_mode == FlowAccessFilterMode.VISIBLE:
            return AIBuilderAuthorization()

        if space_id is None:
            if require_creator and session is not None:
                _ensure_session_creator(self.user, session.actor_user_id)
            return AIBuilderAuthorization()

        require_ai_builder_space_scope(
            scope_filter,
            space_id=space_id,
            raise_scope_mismatch=_raise_scope_mismatch,
        )
        space = await self._space_service().get_space(space_id)
        _ensure_space_flow_edit_permission(
            self._actor_manager.get_space_actor_from_space(space)
        )
        if require_creator and session is not None:
            _ensure_session_creator(self.user, session.actor_user_id)
        return AIBuilderAuthorization(space=space)

    async def open_grant(
        self, scope: BuilderReadScope, action: FlowApiAction
    ) -> BuilderReadGrant:
        """Decide one session-bound read from a fresh access snapshot, in the
        same order as ``authorize``; the flow is the session row's."""
        require_flow_action(self.user, action)
        require_ai_builder_space_scope(
            scope.scope_filter,
            space_id=scope.space_id,
            raise_scope_mismatch=_raise_scope_mismatch,
        )
        reader = self.snapshot_reader or read_access_snapshot
        snapshot = await reader(
            self.user, space_id=scope.space_id, flow_id=scope.flow_id
        )
        if snapshot.space is None:
            raise AIBuilderNotFoundException(
                "Space not found.", code=AIBuilderErrorCode.NOT_FOUND
            )
        _ensure_space_flow_edit_permission(
            self._actor_manager.get_space_actor(snapshot.space)
        )
        _ensure_session_creator(self.user, scope.actor_user_id)
        if scope.flow_id is not None:
            if snapshot.flow_space_id is None:
                raise AIBuilderNotFoundException(
                    "Flow not found.", code=AIBuilderErrorCode.NOT_FOUND
                )
            ensure_flow_in_space(
                flow_space_id=snapshot.flow_space_id, space_id=scope.space_id
            )
        return BuilderReadGrant(scope=scope, action=action)
