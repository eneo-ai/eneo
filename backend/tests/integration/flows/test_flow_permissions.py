"""A flow's `permissions` say what its endpoints let the caller do: each flag
is checked against the endpoint it names, for the draft's owner, another
editor of the space, a viewer of the space, a user outside the space and a
space-scoped service key."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient, Response

from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.database.tables.users_table import users_roles_table
from eneo.flows.domain.flow import Flow
from eneo.flows.published_definition import build_published_definition_json
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

FLAGS = ("can_edit", "can_publish", "can_delete", "can_run", "can_view_runs")


@dataclass(frozen=True)
class World:
    space_id: UUID
    draft_id: str
    published_id: str
    headers: dict[str, dict[str, str]]


async def _flow(
    container: Container, *, space_id: UUID, owner_id: UUID, published: bool
) -> str:
    tenant_id = container.user().tenant_id
    name = f"permissions-{'published' if published else 'draft'}-{uuid4().hex[:6]}"
    flow_repo = container.flow_repo()
    flow = await flow_repo.create(
        Flow(
            tenant_id=tenant_id,
            space_id=space_id,
            name=name,
            created_by_user_id=owner_id,
            owner_user_id=owner_id,
        ),
        tenant_id=tenant_id,
    )
    flow_id = flow.require_persisted_id()
    if published:
        await container.flow_version_repo().create(
            flow_id=flow_id,
            version=1,
            definition_json=build_published_definition_json(
                flow_id=flow_id,
                name=name,
                description=None,
                metadata_json=None,
                steps=[],
            ),
            tenant_id=tenant_id,
        )
        await flow_repo.update(
            flow.model_copy(update={"published_version": 1}), tenant_id=tenant_id
        )
    return str(flow_id)


@pytest.fixture
async def world(
    client: AsyncClient,
    db_container,
    admin_user,
    user_factory,
    flow_process_auth_headers,
) -> World:
    async with db_container() as container:
        session = container.session()
        tenant_id = admin_user.tenant_id
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-author-{uuid4().hex[:8]}",
                permissions=[
                    Permission.FLOWS_VIEW,
                    Permission.FLOWS_RUN,
                    Permission.FLOWS_MANAGE,
                ],
                tenant_id=tenant_id,
            )
        )
        users = {
            label: await user_factory(session)
            for label in ("owner", "editor", "viewer", "outsider")
        }
        for user in users.values():
            await session.execute(
                sa.insert(users_roles_table).values(user_id=user.id, role_id=role.id)
            )
        org = (
            await session.scalars(
                sa.select(Spaces).where(
                    Spaces.tenant_id == tenant_id,
                    Spaces.user_id.is_(None),
                    Spaces.tenant_space_id.is_(None),
                )
            )
        ).one()
        space = Spaces(
            name=f"Permissions {uuid4().hex[:6]}",
            tenant_id=tenant_id,
            tenant_space_id=org.id,
        )
        session.add(space)
        await session.flush()
        space_id = space.id
        session.add_all(
            [
                SpacesUsers(
                    space_id=space.id, user_id=users["owner"].id, role="editor"
                ),
                SpacesUsers(
                    space_id=space.id, user_id=users["editor"].id, role="editor"
                ),
                SpacesUsers(
                    space_id=space.id, user_id=users["viewer"].id, role="viewer"
                ),
                # Space-scoped keys are created by an admin of that space.
                SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"),
            ]
        )
        await session.flush()
        owner_id = users["owner"].id
        draft_id = await _flow(
            container, space_id=space.id, owner_id=owner_id, published=False
        )
        published_id = await _flow(
            container, space_id=space.id, owner_id=owner_id, published=True
        )
        headers: dict[str, dict[str, str]] = {}
        for label, user in users.items():
            in_db = await container.user_repo().get_user_by_id(user.id)
            token = container.auth_service().create_access_token_for_user(in_db)
            headers[label] = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"flow-permissions-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "admin",
            "scope_type": "space",
            "scope_id": str(space_id),
            "ownership": "service",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "resource_permissions": {"flows": "admin"},
        },
        headers=dict(flow_process_auth_headers),
    )
    assert created.status_code == 201, created.text
    headers["service key"] = {"X-API-Key": created.json()["secret"]}
    return World(
        space_id=space_id,
        draft_id=draft_id,
        published_id=published_id,
        headers=headers,
    )


def _code(response: Response) -> object:
    try:
        return response.json().get("code")
    except ValueError:
        return None


def _allowed(response: Response, *passed: tuple[int, str | None]) -> bool:
    """True when the endpoint let the caller through its access checks: it
    answered as ``passed`` says a later check does. False for 403 and 404."""
    if response.status_code in (403, 404):
        return False
    assert (response.status_code, _code(response)) in passed, response.text
    return True


async def _endpoints(
    client: AsyncClient, headers: Mapping[str, str], flow_id: str
) -> dict[str, bool]:
    """What each endpoint lets the caller do, without changing the flow: every
    request is refused by a check after the access checks."""
    stale = {"expected_revision": 10_000}
    edit = await client.patch(
        f"/api/v1/flows/{flow_id}/editor/",
        json={**stale, "definition": {}},
        headers=headers,
    )
    publish = await client.post(
        f"/api/v1/flows/{flow_id}/publish/", params=stale, headers=headers
    )
    run = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={"input_payload_json": {}, "expected_flow_version": 10_000},
        headers=headers,
    )
    runs = await client.get(f"/api/v1/flows/{flow_id}/runs/", headers=headers)
    return {
        "can_edit": _allowed(edit, (400, "stale_revision")),
        "can_publish": _allowed(publish, (400, "stale_revision")),
        "can_run": _allowed(
            run, (400, "flow_not_published"), (400, "flow_run_stale_version")
        ),
        "can_view_runs": _allowed(runs, (200, None)),
    }


async def _flags(
    client: AsyncClient, headers: Mapping[str, str], world: World, flow_id: str
) -> dict[str, Any] | None:
    """The flags of the flow read alone, checked against its list item; None
    when the caller cannot read it."""
    read = await client.get(f"/api/v1/flows/{flow_id}/", headers=headers)
    listed = await client.get(
        "/api/v1/flows/",
        params={"space_id": str(world.space_id), "limit": 200},
        headers=headers,
    )
    items = (
        {item["id"]: item for item in listed.json()["items"]}
        if listed.status_code == 200
        else {}
    )
    if read.status_code in (403, 404):
        assert flow_id not in items
        return None
    assert read.status_code == 200, read.text
    flags = read.json()["permissions"]
    assert set(flags) == set(FLAGS)
    if flow_id in items:
        assert items[flow_id]["permissions"] == flags
    return flags


async def test_each_flag_is_what_its_endpoint_allows(client: AsyncClient, world: World):
    expected = {
        # principal: (draft flags, published flags); None = cannot read the flow
        "owner": ((True, True, True, True, True), (True, True, True, True, True)),
        "editor": (
            (False, False, False, True, True),
            (False, False, False, True, True),
        ),
        "viewer": (None, (False, False, False, True, True)),
        "outsider": (None, None),
        "service key": (
            (False, False, False, False, True),
            (False, False, False, True, True),
        ),
    }
    for principal, headers in world.headers.items():
        for flow_id, wanted in zip(
            (world.draft_id, world.published_id), expected[principal], strict=True
        ):
            flags = await _flags(client, headers, world, flow_id)
            endpoints = await _endpoints(client, headers, flow_id)
            where = f"{principal} on {'draft' if flow_id == world.draft_id else 'published'}"
            if wanted is None:
                assert flags is None, where
                assert not any(endpoints.values()), (where, endpoints)
                continue
            assert flags is not None, where
            assert tuple(flags[flag] for flag in FLAGS) == wanted, (where, flags)
            assert {flag: flags[flag] for flag in endpoints} == endpoints, where

    # Deleting goes last: only a caller whose flag allows it gets through.
    for flow_id in (world.draft_id, world.published_id):
        for principal in ("editor", "viewer", "outsider", "service key"):
            refused = await client.delete(
                f"/api/v1/flows/{flow_id}/", headers=world.headers[principal]
            )
            assert refused.status_code in (403, 404), (principal, refused.text)
        deleted = await client.delete(
            f"/api/v1/flows/{flow_id}/", headers=world.headers["owner"]
        )
        assert deleted.status_code == 204, deleted.text
