"""A run read reads the flow's authorization row and the caller's facts once.

The flow gate and every run service of a request share the request
Container's one access policy, whose memo answers each later question.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from dependency_injector import providers

from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.api import flow_access_context
from eneo.flows.domain.flow import FlowRun, FlowRunStatus
from eneo.flows.flow_evidence_policy import FlowHistoryAccessContext
from eneo.main.container.container import Container
from eneo.main.container.container_overrides import override_user
from eneo.main.exceptions import NotFoundException
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.users.user import UserInDB


class _FlowRepo:
    def __init__(self, context: FlowHistoryAccessContext) -> None:
        self.context = context
        self.reads: list[bool] = []

    async def get_history_access_context(
        self, *, flow_id: UUID, tenant_id: UUID, include_retired: bool
    ) -> FlowHistoryAccessContext:
        _ = (flow_id, tenant_id)
        self.reads.append(include_retired)
        if self.context.retired and not include_retired:
            raise NotFoundException("Flow not found.")
        return self.context


class _SpaceService:
    def __init__(self) -> None:
        self.reads: list[UUID] = []

    async def get_space_access_facts(self, id: UUID) -> SimpleNamespace:
        self.reads.append(id)
        return SimpleNamespace(id=id)


class _Actor:
    def can_read_flows(self) -> bool:
        return True

    def can_read_flow(self, flow: object) -> bool:
        _ = flow
        return True

    def get_current_role(self) -> str:
        return "member"


class _ActorManager:
    def get_space_actor(self, facts: object) -> _Actor:
        _ = facts
        return _Actor()


class _RunRepo:
    def __init__(self, run: FlowRun) -> None:
        self.run = run
        # The evidence service builds its corrections repo on this session.
        self.session = MagicMock()

    async def get(self, **_kwargs: object) -> FlowRun:
        return self.run

    async def get_status(self, **_kwargs: object) -> FlowRun:
        return self.run

    async def list_statuses(self, **_kwargs: object) -> list[FlowRun]:
        return [self.run]

    async def count_statuses(self, **_kwargs: object) -> dict[FlowRunStatus, int]:
        return {}

    async def has_step_attempts(self, **_kwargs: object) -> bool:
        return False


class _Request:
    """One request's Container over counting fakes."""

    def __init__(self, user: UserInDB, *, retired: bool = False) -> None:
        now = datetime.now(timezone.utc)
        flow_id = uuid4()
        self.flow_repo = _FlowRepo(
            FlowHistoryAccessContext(
                flow_id=flow_id,
                space_id=uuid4(),
                published=True,
                retired=retired,
                sensitive=False,
                evidence_export_allowed=True,
                classification_level=0,
            )
        )
        self.space_service = _SpaceService()
        self.run = FlowRun(
            id=uuid4(),
            flow_id=flow_id,
            flow_version=1,
            principal_type=PrincipalType.USER.value,
            principal_user_id=user.id,
            tenant_id=user.tenant_id,
            trace_id=uuid4(),
            status=FlowRunStatus.COMPLETED,
            cancelled_at=None,
            input_payload_json=None,
            output_payload_json=None,
            job_id=None,
            evidence_classification_level=0,
            created_at=now,
            updated_at=now,
        )
        self.container = Container(session=providers.Object(MagicMock()))
        override_user(self.container, user)
        self.container.override_providers(
            flow_repo=providers.Object(self.flow_repo),
            flow_run_repo=providers.Object(_RunRepo(self.run)),
            space_service=providers.Object(self.space_service),
            actor_manager=providers.Object(_ActorManager()),
            # Built into the run services' file collaborators; never read here.
            object_content_service=providers.Object(MagicMock()),
        )

    async def gate(self, *, history: bool = True) -> None:
        await flow_access_context.enforce_flow_scope(
            SimpleNamespace(state=SimpleNamespace()),
            self.container,
            flow_id=self.run.flow_id,
            allow_service_key_principals=True,
            history=history,
        )


def _with_permissions(user: UserInDB, *permissions: Permission) -> UserInDB:
    role = RoleInDB(
        id=uuid4(), name="Role", tenant_id=user.tenant_id, permissions=[*permissions]
    )
    return user.model_copy(update={"roles": [role]})


@pytest.fixture
def member(user: UserInDB) -> UserInDB:
    return _with_permissions(user, Permission.FLOWS)


@pytest.fixture(autouse=True)
def _unscoped_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        flow_access_context,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )


async def _status(request: _Request) -> None:
    run = request.run
    await request.container.flow_run_service().get_run_status(
        run_id=run.id, flow_id=run.flow_id, history=True
    )


async def _list(request: _Request) -> None:
    run_service = request.container.flow_run_service()
    await run_service.list_run_statuses(flow_id=request.run.flow_id, history=True)
    await run_service.count_run_statuses(flow_id=request.run.flow_id, history=True)


async def _detail(request: _Request) -> None:
    run = request.run
    await request.container.flow_run_service().get_run(
        run_id=run.id, flow_id=run.flow_id, access_kind="content", history=True
    )


async def _evidence(request: _Request) -> None:
    # The review and transcript routes: the run, then its evidence, from two
    # services.
    run = request.run
    await request.container.flow_run_service().get_run(
        run_id=run.id, flow_id=run.flow_id, access_kind="content", history=True
    )
    await request.container.flow_run_evidence_service().get_run(
        run_id=run.id, flow_id=run.flow_id, access_kind="evidence_view", history=True
    )


def test_one_policy_serves_the_gate_and_every_run_service_of_a_request(
    member: UserInDB,
) -> None:
    container = _Request(member).container

    policy = container.flow_run_access_policy()

    assert container.flow_run_access_policy() is policy
    assert container.flow_run_service().access_policy is policy
    assert container.flow_run_evidence_service().access_policy is policy
    assert policy.user is member


def test_each_request_container_holds_its_own_policy(member: UserInDB) -> None:
    other = member.model_copy(update={"id": uuid4()})

    policy = _Request(member).container.flow_run_access_policy()
    other_policy = _Request(other).container.flow_run_access_policy()

    assert policy is not other_policy
    assert policy.user is member
    assert other_policy.user is other


@pytest.mark.parametrize(
    "read",
    [_status, _list, _detail, _evidence],
    ids=["status", "list", "detail", "evidence"],
)
async def test_a_run_read_reads_the_flow_row_and_the_callers_facts_once(
    member: UserInDB, read: Callable[[_Request], Awaitable[None]]
) -> None:
    request = _Request(member)

    await request.gate()
    await read(request)

    assert request.flow_repo.reads == [True]
    assert request.space_service.reads == [request.flow_repo.context.space_id]


async def test_a_tenant_admin_reads_the_callers_facts_once(user: UserInDB) -> None:
    request = _Request(_with_permissions(user, Permission.ADMIN, Permission.FLOWS))

    await request.gate()
    await _status(request)
    await _list(request)

    assert request.flow_repo.reads == [True]
    assert request.space_service.reads == [request.flow_repo.context.space_id]


async def test_a_live_read_of_a_retired_flow_is_not_found_after_a_history_read(
    member: UserInDB,
) -> None:
    request = _Request(member, retired=True)
    await request.gate()
    await _status(request)

    with pytest.raises(NotFoundException):
        await request.gate(history=False)
    with pytest.raises(NotFoundException):
        await request.container.flow_run_service().get_run_status(
            run_id=request.run.id, flow_id=request.run.flow_id
        )
    assert request.flow_repo.reads == [True, False, False]
