"""A Flows run read stays within its statement budget.

The flow gate and the run services of one request share the request's run
access policy, so each polled read reads the caller's space roles in one
`spaces_users` and one `spaces_user_groups` statement, whoever reads, and a
warmed read issues no more statements than its route's ceiling.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.flows.api import flow_run_lifecycle_router
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_SPACES_USERS = re.compile(r"\bFROM spaces_users\b")
_SPACES_USER_GROUPS = re.compile(r"\bFROM spaces_user_groups\b")

# Warmed statements per route and reader, at the measured counts. Lower a
# ceiling when a change saves statements; raise one only with the reason.
_CEILINGS: dict[str, dict[str, int]] = {
    "space member": {
        "status": 13,
        "graph": 14,
        "run detail": 19,
        "steps": 19,
        "runs list": 14,
        "evidence": 39,
    },
    "tenant admin": {
        "status": 13,
        "graph": 14,
        "run detail": 18,
        "steps": 19,
        "runs list": 14,
        "evidence": 39,
    },
}


async def _no_dispatch(*, run_id, tenant_id, expected_revision) -> None:
    _ = (run_id, tenant_id, expected_revision)


async def _member_headers(db_container, admin_user, space_id: str) -> dict[str, str]:
    """A space editor who may run flows and view their traces."""
    suffix = uuid4().hex[:8]
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"Run reader {suffix}",
                permissions=[Permission.FLOWS_RUN, Permission.FLOWS_TRACE],
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"run-reader-{suffix}@example.com",
                username=f"run_reader_{suffix}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        await container.session().execute(
            sa.text(
                "INSERT INTO spaces_users (space_id, user_id, role) "
                "VALUES (:space_id, :user_id, :role)"
            ),
            {
                "space_id": space_id,
                "user_id": str(user.id),
                "role": SpaceRoleValue.EDITOR.value,
            },
        )
        token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def _statements() -> Iterator[list[str]]:
    engine = sessionmanager._engine
    assert engine is not None
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _many) -> None:
        statements.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)


async def _read(client, url: str, headers: Mapping[str, str]) -> list[str]:
    # The first read warms per-process caches; the second is the one counted.
    for _ in range(2):
        with _statements() as statements:
            response = await client.get(url, headers=headers)
        assert response.status_code == 200, (url, response.text)
    return statements


async def test_each_run_read_stays_within_its_statement_budget(
    client,
    db_container,
    admin_user,
    flow_process_auth_headers,
    create_published_compose_text_flow,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _no_dispatch,
    )
    admin = flow_process_auth_headers
    flow = await create_published_compose_text_flow(client, admin)
    base = f"/api/v1/flows/{flow.flow_id}"
    space_id = (await client.get(f"{base}/", headers=admin)).json()["space_id"]
    member = await _member_headers(db_container, admin_user, space_id)

    for reader, headers in (("tenant admin", admin), ("space member", member)):
        created = await client.post(
            f"{base}/runs/",
            json={
                "expected_flow_version": flow.published_version,
                "input_payload_json": {"text": "budget"},
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        for route, url in {
            "status": f"{base}/runs/{run_id}/status/",
            "graph": f"{base}/graph/?run_id={run_id}",
            "run detail": f"{base}/runs/{run_id}/",
            "steps": f"{base}/runs/{run_id}/steps/",
            "runs list": f"{base}/runs/?limit=25",
            "evidence": f"{base}/runs/{run_id}/evidence/",
        }.items():
            statements = await _read(client, url, headers)
            facts = (
                sum(bool(_SPACES_USERS.search(s)) for s in statements),
                sum(bool(_SPACES_USER_GROUPS.search(s)) for s in statements),
            )
            assert facts == (1, 1), (reader, route, len(statements))
            ceiling = _CEILINGS[reader][route]
            assert len(statements) <= ceiling, (
                f"{reader} {route} read issued {len(statements)} statements, "
                f"ceiling {ceiling}:\n" + "\n---\n".join(statements)
            )
