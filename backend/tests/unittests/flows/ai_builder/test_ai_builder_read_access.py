"""Builder read authorization without a Request.

A grant for a session-bound read is decided from a fresh access snapshot read
on every call. These tests drive the seam with a real ``SpaceActor`` over the
snapshot's facts, so the decision is the space owner's rule, not a stub.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.actors.actor_factory import ActorFactory
from eneo.actors.actor_manager import ActorManager
from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceRoleFact
from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderSession,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_read_access import (
    BuilderAccessSnapshot,
    BuilderReadAccess,
    scope_for_session,
)
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.roles.permissions import Permission

_BUILDER = [Permission.FLOWS, Permission.FLOWS_AI_BUILDER_REVIEW]


def _user(*, permissions: Sequence[Permission] = _BUILDER, api_key=None):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=list(permissions),
        user_groups_ids=[],
        active_api_key=api_key,
    )


def _facts(space_id: UUID, user_id: UUID, role: str | None) -> SpaceAccessFacts:
    return SpaceAccessFacts(
        id=space_id,
        user_id=None,
        tenant_space_id=uuid4(),
        members=(
            {user_id: SpaceRoleFact(id=user_id, role=role)} if role is not None else {}
        ),
        group_members={},
        default_assistant_id=None,
        assistant_ids=frozenset(),
        app_ids=frozenset(),
    )


def _session(*, user, space_id: UUID, flow_id: UUID | None = None, actor=None):
    return BuilderSession(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=space_id,
        flow_id=flow_id,
        target_kind=TargetKind.EDIT if flow_id else TargetKind.CREATE,
        status=SessionStatus.CHATTING,
        actor_user_id=actor or user.id,
    )


class _Snapshots:
    """Answers each grant from the next scripted state, and counts reads."""

    def __init__(self, user, states: list[tuple[str | None, UUID | None]]) -> None:
        self.user = user
        self.states = states
        self.reads: list[tuple[UUID, UUID | None]] = []

    async def __call__(self, user, *, space_id: UUID, flow_id: UUID | None):
        assert user is self.user
        self.reads.append((space_id, flow_id))
        role, flow_space_id = self.states[min(len(self.reads), len(self.states)) - 1]
        return BuilderAccessSnapshot(
            space=_facts(space_id, user.id, role) if role != "absent" else None,
            flow_space_id=flow_space_id if flow_id is not None else None,
        )


def _access(user, snapshots=None, *, space_service=None) -> BuilderReadAccess:
    return BuilderReadAccess(
        user=user,
        space_service=lambda: space_service or AsyncMock(),
        actor_manager=ActorManager(user=user, factory=ActorFactory()),
        snapshot_reader=snapshots,
    )


@pytest.mark.anyio
async def test_a_role_lowered_between_two_grants_refuses_the_second() -> None:
    user = _user()
    space_id, flow_id = uuid4(), uuid4()
    snapshots = _Snapshots(user, [("editor", space_id), ("viewer", space_id)])
    scope = scope_for_session(
        _session(user=user, space_id=space_id, flow_id=flow_id), ScopeFilter()
    )
    access = _access(user, snapshots)

    await access.open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)
    with pytest.raises(UnauthorizedException) as refused:
        await access.open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)

    assert refused.value.code == "insufficient_space_permission"
    assert refused.value.context == {"auth_layer": "space_membership"}
    # Each grant read its own snapshot; nothing was carried over.
    assert snapshots.reads == [(space_id, flow_id), (space_id, flow_id)]


@pytest.mark.anyio
async def test_a_removed_member_and_a_removed_space_are_refused() -> None:
    user = _user()
    space_id = uuid4()
    scope = scope_for_session(_session(user=user, space_id=space_id), ScopeFilter())

    with pytest.raises(UnauthorizedException) as removed:
        await _access(user, _Snapshots(user, [(None, None)])).open_grant(
            scope, FlowApiAction.BUILDER_MESSAGE_SEND
        )
    assert removed.value.code == "insufficient_space_permission"

    with pytest.raises(NotFoundException):
        await _access(user, _Snapshots(user, [("absent", None)])).open_grant(
            scope, FlowApiAction.BUILDER_MESSAGE_SEND
        )


@pytest.mark.anyio
async def test_a_grant_never_reads_the_space_aggregate() -> None:
    """The operation's own session can hold a Space loaded before a
    revocation; a grant must not consult it."""
    user = _user()
    space_id = uuid4()
    space_service = AsyncMock()
    scope = scope_for_session(_session(user=user, space_id=space_id), ScopeFilter())

    await _access(
        user, _Snapshots(user, [("editor", None)]), space_service=space_service
    ).open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)

    space_service.get_space.assert_not_called()


@pytest.mark.anyio
async def test_a_session_of_another_principal_is_refused() -> None:
    user = _user()
    space_id = uuid4()
    scope = scope_for_session(
        _session(user=user, space_id=space_id, actor=uuid4()), ScopeFilter()
    )

    with pytest.raises(UnauthorizedException) as refused:
        await _access(user, _Snapshots(user, [("editor", None)])).open_grant(
            scope, FlowApiAction.BUILDER_MESSAGE_SEND
        )

    assert refused.value.code == "session_creator_required"


@pytest.mark.anyio
async def test_the_flow_is_pinned_from_the_session_row() -> None:
    user = _user()
    space_id, flow_id = uuid4(), uuid4()
    scope = scope_for_session(
        _session(user=user, space_id=space_id, flow_id=flow_id), ScopeFilter()
    )

    moved = _Snapshots(user, [("editor", uuid4())])
    with pytest.raises(Exception) as mismatch:
        await _access(user, moved).open_grant(scope, FlowApiAction.BUILDER_REVIEW)
    assert getattr(mismatch.value, "code", None) == "flow_space_mismatch"
    assert moved.reads == [(space_id, flow_id)]

    with pytest.raises(NotFoundException):
        await _access(user, _Snapshots(user, [("editor", None)])).open_grant(
            scope, FlowApiAction.BUILDER_REVIEW
        )


@pytest.mark.anyio
async def test_tenant_permission_and_key_scope_refuse_before_any_read() -> None:
    space_id = uuid4()

    user = _user(permissions=[Permission.FLOWS_MANAGE])
    snapshots = _Snapshots(user, [("owner", None)])
    scope = scope_for_session(_session(user=user, space_id=space_id), ScopeFilter())
    with pytest.raises(UnauthorizedException) as tenant:
        await _access(user, snapshots).open_grant(
            scope, FlowApiAction.BUILDER_MESSAGE_SEND
        )
    assert tenant.value.code == "insufficient_tenant_permission"

    user = _user()
    snapshots = _Snapshots(user, [("owner", None)])
    scope = scope_for_session(
        _session(user=user, space_id=space_id),
        ScopeFilter(scope_type="space", space_id=uuid4()),
    )
    with pytest.raises(UnauthorizedException) as key:
        await _access(user, snapshots).open_grant(
            scope, FlowApiAction.BUILDER_MESSAGE_SEND
        )
    assert key.value.code == "insufficient_scope"
    assert snapshots.reads == []
