"""Run starters are named only inside the caller's tenant and, for a service
key, only on its own runs."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.api.flow_run_started_by import FlowRunStartedByPresenter
from eneo.flows.domain.flow import FlowRunStatusSnapshot
from eneo.flows.enums import FlowRunStatus
from eneo.flows.infrastructure.flow_run_starter_repo import (
    FlowRunStarterServicePrincipal,
    FlowRunStarterUser,
)
from eneo.flows.principal import FlowPrincipal

TENANT_ID = uuid4()


def _run(
    *,
    user_id: UUID | None = None,
    service_id: UUID | None = None,
    tenant_id: UUID = TENANT_ID,
) -> FlowRunStatusSnapshot:
    now = datetime.now(timezone.utc)
    return FlowRunStatusSnapshot(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=(
            PrincipalType.SERVICE_KEY if service_id is not None else PrincipalType.USER
        ),
        principal_user_id=user_id,
        principal_service_id=service_id,
        tenant_id=tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )


def _presenter(
    caller: FlowPrincipal,
    *,
    users: dict[UUID, FlowRunStarterUser] | None = None,
    service_principals: dict[UUID, FlowRunStarterServicePrincipal] | None = None,
) -> tuple[FlowRunStartedByPresenter, AsyncMock]:
    repo = AsyncMock()
    repo.list_users = AsyncMock(return_value=users or {})
    repo.list_service_principals = AsyncMock(return_value=service_principals or {})
    return (
        FlowRunStartedByPresenter(repo=repo, tenant_id=TENANT_ID, caller=caller),
        repo,
    )


def _user_caller() -> FlowPrincipal:
    return FlowPrincipal(principal_type=PrincipalType.USER, principal_user_id=uuid4())


async def test_a_user_starter_is_named_by_username_and_carries_the_email():
    user_id = uuid4()
    run = _run(user_id=user_id)
    presenter, repo = _presenter(
        _user_caller(),
        users={
            user_id: FlowRunStarterUser(
                id=user_id, username="Anna Lind", email="anna@example.com"
            )
        },
    )

    started_by = await presenter.for_run(run)

    assert started_by is not None
    assert started_by.principal_type is PrincipalType.USER
    assert started_by.id == user_id
    assert started_by.display_name == "Anna Lind"
    assert started_by.email == "anna@example.com"
    repo.list_users.assert_awaited_once()
    assert repo.list_users.await_args.kwargs["tenant_id"] == TENANT_ID


async def test_a_user_without_a_username_is_named_by_email():
    user_id = uuid4()
    presenter, _repo = _presenter(
        _user_caller(),
        users={
            user_id: FlowRunStarterUser(
                id=user_id, username="  ", email="anna@example.com"
            )
        },
    )

    started_by = await presenter.for_run(_run(user_id=user_id))

    assert started_by is not None
    assert started_by.display_name == "anna@example.com"


async def test_a_starter_that_no_longer_resolves_keeps_its_id_without_a_name():
    user_id = uuid4()
    presenter, _repo = _presenter(_user_caller())

    started_by = await presenter.for_run(_run(user_id=user_id))

    assert started_by is not None
    assert started_by.id == user_id
    assert started_by.display_name is None
    assert started_by.email is None


async def test_a_service_key_starter_is_named_by_the_key_name_without_email():
    service_id = uuid4()
    presenter, _repo = _presenter(
        _user_caller(),
        service_principals={
            service_id: FlowRunStarterServicePrincipal(
                id=service_id, display_name="Case intake"
            )
        },
    )

    started_by = await presenter.for_run(_run(service_id=service_id))

    assert started_by is not None
    assert started_by.principal_type is PrincipalType.SERVICE_KEY
    assert started_by.id == service_id
    assert started_by.display_name == "Case intake"
    assert started_by.email is None


async def test_a_service_key_caller_is_named_only_on_its_own_runs():
    own_service_id = uuid4()
    other_user_id = uuid4()
    caller = FlowPrincipal(
        principal_type=PrincipalType.SERVICE_KEY,
        principal_service_id=own_service_id,
    )
    own_run = _run(service_id=own_service_id)
    other_run = _run(user_id=other_user_id)
    presenter, repo = _presenter(
        caller,
        users={
            other_user_id: FlowRunStarterUser(
                id=other_user_id, username="Someone", email="someone@example.com"
            )
        },
        service_principals={
            own_service_id: FlowRunStarterServicePrincipal(
                id=own_service_id, display_name="Own key"
            )
        },
    )

    started_by = await presenter.for_runs([own_run, other_run])

    assert set(started_by) == {own_run.id}
    assert list(repo.list_users.await_args.kwargs["user_ids"]) == []


async def test_a_run_of_another_tenant_is_never_named():
    user_id = uuid4()
    presenter, _repo = _presenter(
        _user_caller(),
        users={
            user_id: FlowRunStarterUser(
                id=user_id, username="Anna", email="anna@example.com"
            )
        },
    )

    started_by = await presenter.for_run(_run(user_id=user_id, tenant_id=uuid4()))

    assert started_by is None
