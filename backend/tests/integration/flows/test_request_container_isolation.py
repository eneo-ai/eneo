"""Each authenticated request's container is its own, however requests overlap.

A request container copies Container's providers when the request first uses
them (eneo.main.container.request_container). These requests run on the real
app and Postgres, from two tenants with JWT and API-key principals, and are
held at checkpoints inside and after authentication so that they interleave.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.database.database import sessionmanager
from eneo.flows.api import flow_run_lifecycle_router
from eneo.main.container.container import Container
from eneo.main.container.request_container import request_container
from eneo.main.models import ModelId
from eneo.questions.questions_repo import QuestionRepository
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.server.dependencies import container as container_dependency
from eneo.server.dependencies.container import get_container
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.users.user import UserAdd, UserState
from eneo.users.user_service import UserService
from tests.fixtures import mint_v2_api_key

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# Providers a status read reaches, JWT or API key: the copies it touched and
# every provider they reach, override Objects included, at the measured
# count. Lower it when wiring
# shrinks; raise it only with the reason.
_STATUS_COPY_CEILING = 74

Headers = dict[str, str]
_user_container = get_container(with_user=True)


@dataclass
class _Checkpoints:
    """Where the probe routes and authentication wait, by point and request tag."""

    barriers: dict[str, asyncio.Barrier] = field(default_factory=dict)
    holds: dict[tuple[str, str], Callable[[], Awaitable[None]]] = field(
        default_factory=dict
    )
    seen: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def reach(self, point: str, tag: str = "") -> None:
        barrier = self.barriers.get(point)
        if barrier is not None:
            await asyncio.wait_for(barrier.wait(), 20)
        hold = self.holds.get((point, tag))
        if hold is not None:
            await hold()


def _question_repo_in_a_thread(
    container: Annotated[Container, Depends(_user_container)],
) -> tuple[QuestionRepository, bool, int]:
    """A sync dependency: FastAPI runs it in the threadpool."""
    first_use = "question_repo" not in container.providers
    return container.question_repo(), first_use, threading.get_ident()


def _probe_router(points: _Checkpoints) -> APIRouter:
    router = APIRouter(prefix="/request-container-probe")
    access = endpoint_access(
        authentication=Authentication.USER,
        authorization=Authorization.AUTHENTICATED,
        reason="Request container isolation test route.",
    )

    @router.get("/whoami/")
    @access
    async def whoami(
        request: Request,
        container: Annotated[Container, Depends(_user_container)],
        flow_id: UUID | None = None,
    ) -> dict[str, object]:
        tag = request.headers["x-probe-tag"]
        await points.reach("after_auth", tag)
        policy = container.flow_run_access_policy()
        session = container.session()
        # Read before this request asks the policy anything.
        fresh_memo = (
            not policy._space_access_by_flow_id and not policy._flow_context_by_mode
        )
        points.seen[tag] = {"container": container, "session": session}
        await points.reach("after_policy", tag)
        if flow_id is not None:
            await policy.load_flow_context(flow_id=flow_id)
        user, tenant = container.user(), container.tenant()
        loaded = await container.user_repo().get_user_by_id_and_tenant_id(
            id=user.id, tenant_id=tenant.id
        )
        return {
            "tag": tag,
            "container": id(container),
            "session": id(session),
            "policy": id(policy),
            "user": str(user.id),
            "email": user.email,
            "tenant": str(tenant.id),
            "api_key": user.active_api_key is not None,
            "policy_user": str(policy.user.id),
            "policy_is_singleton": container.flow_run_access_policy() is policy,
            "fresh_memo": fresh_memo,
            "memo_used": bool(policy._flow_context_by_mode),
            "policy_session": policy.flow_repo.session is session
            and policy.flow_run_repo.session is session,
            "user_service_session": container.user_service().repo.session is session,
            "db_email": loaded.email if loaded else None,
            "in_transaction": session.in_transaction(),
        }

    @router.get("/stream/")
    @access
    async def stream(
        container: Annotated[Container, Depends(_user_container)],
    ) -> StreamingResponse:
        async def body():
            user = container.user()
            for chunk in range(3):
                await asyncio.sleep(0)
                row = await container.user_repo().get_user_by_id_and_tenant_id(
                    id=user.id, tenant_id=user.tenant_id
                )
                assert row is not None
                in_transaction = container.session().in_transaction()
                yield f"{chunk}:{row.email}:{in_transaction}\n".encode()

        return StreamingResponse(body(), media_type="text/plain")

    @router.post("/write/")
    @access
    async def write(
        container: Annotated[
            Container,
            Depends(get_container(with_user=True, transaction_scope="function")),
        ],
    ) -> dict[str, str]:
        username = f"rc-{uuid4().hex[:8]}"
        await container.session().execute(
            sa.text("UPDATE users SET username = :username WHERE id = :id"),
            {"username": username, "id": str(container.user().id)},
        )
        return {"username": username}

    @router.get("/threadpool/")
    @access
    async def threadpool(
        container: Annotated[Container, Depends(_user_container)],
        resolved: Annotated[
            tuple[QuestionRepository, bool, int], Depends(_question_repo_in_a_thread)
        ],
    ) -> dict[str, bool]:
        repo, first_use, thread = resolved
        return {
            "copied_off_the_loop": first_use and thread != threading.get_ident(),
            "request_session": repo.session is container.session(),
        }

    return router


@pytest.fixture
def points(app) -> _Checkpoints:
    checkpoints = _Checkpoints()
    app.include_router(_probe_router(checkpoints), prefix="/api/v1")
    return checkpoints


@pytest.fixture
def interleaved_authentication(points, monkeypatch) -> None:
    """Every request enters and leaves authentication at the auth barriers."""
    authenticate = UserService.authenticate

    async def interleaved(self, *args, **kwargs):
        await points.reach("auth_in")
        try:
            return await authenticate(self, *args, **kwargs)
        finally:
            await points.reach("auth_out")

    monkeypatch.setattr(UserService, "authenticate", interleaved)


async def _no_dispatch(*, run_id, tenant_id, expected_revision) -> None:
    _ = (run_id, tenant_id, expected_revision)


async def _space_editor(db_container, tenant_id: UUID, space_id: str) -> Headers:
    """A space editor who may run flows and view their traces."""
    suffix = uuid4().hex[:8]
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"Run reader {suffix}",
                permissions=[Permission.FLOWS_RUN, Permission.FLOWS_TRACE],
                tenant_id=tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"run-reader-{suffix}@example.com",
                username=f"run_reader_{suffix}",
                state=UserState.ACTIVE,
                tenant_id=tenant_id,
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


async def _two_keys(
    container: Container, tenant_id: UUID, user_id: UUID
) -> tuple[Headers, Headers]:
    first, second = [
        await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=tenant_id,
            user_id=user_id,
            prefix="sk",
        )
        for _ in range(2)
    ]
    return {"X-API-Key": first.key}, {"X-API-Key": second.key}


@dataclass(frozen=True)
class _Principal:
    """Two credentials for one principal: one per concurrent request, since
    a key's row is updated when it is used."""

    headers: tuple[Headers, Headers]
    user_id: str | None
    tenant_id: str
    api_key: bool


@dataclass(frozen=True)
class _World:
    principals: dict[str, _Principal]
    flow_id: str
    base: str
    run_id: str


@pytest.fixture
async def world(
    client,
    db_container,
    admin_user,
    flow_process_auth_headers,
    create_published_compose_text_flow,
    super_admin_token,
    monkeypatch,
) -> _World:
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        _no_dispatch,
    )
    admin = dict(flow_process_auth_headers)
    flow = await create_published_compose_text_flow(client, admin)
    base = f"/api/v1/flows/{flow.flow_id}"
    space_id = (await client.get(f"{base}/", headers=admin)).json()["space_id"]
    editor = await _space_editor(db_container, admin_user.tenant_id, space_id)
    run = await client.post(
        f"{base}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {"text": "isolation"},
        },
        headers=admin,
    )
    assert run.status_code == 201, run.text

    name_b = f"rc-tenant-b-{uuid4().hex[:6]}"
    tenant_b = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={"name": name_b, "display_name": name_b, "state": "active"},
        headers={"X-API-Key": super_admin_token},
    )
    assert tenant_b.status_code == 200, tenant_b.text
    tenant_b_id = UUID(tenant_b.json()["id"])
    async with db_container() as container:
        # A tenant-scoped key acts only for an admin.
        admin_b = await container.role_repo().create_role(
            RoleCreate(
                name="Tenant B admin",
                permissions=[Permission.ADMIN],
                tenant_id=tenant_b_id,
            )
        )
        user_b = await container.user_repo().add(
            UserAdd(
                email=f"rc-b-{uuid4().hex[:8]}@example.com",
                username=f"rc_b_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=tenant_b_id,
                roles=[ModelId(id=admin_b.id)],
            )
        )
        jwt_b = {
            "Authorization": "Bearer "
            + container.auth_service().create_access_token_for_user(user_b)
        }
        keys_a = await _two_keys(container, admin_user.tenant_id, admin_user.id)
        keys_b = await _two_keys(container, tenant_b_id, user_b.id)
    tenant_a, admin_id = str(admin_user.tenant_id), str(admin_user.id)
    return _World(
        principals={
            "A-admin-jwt": _Principal((admin, admin), admin_id, tenant_a, False),
            "A-editor-jwt": _Principal((editor, editor), None, tenant_a, False),
            "A-admin-key": _Principal(keys_a, admin_id, tenant_a, True),
            "B-admin-jwt": _Principal(
                (jwt_b, jwt_b), str(user_b.id), str(tenant_b_id), False
            ),
            "B-admin-key": _Principal(keys_b, str(user_b.id), str(tenant_b_id), True),
        },
        flow_id=flow.flow_id,
        base=base,
        run_id=run.json()["id"],
    )


async def _whoami(client, headers: Headers, tag: str, flow_id: str | None = None):
    return await client.get(
        "/api/v1/request-container-probe/whoami/",
        params={} if flow_id is None else {"flow_id": flow_id},
        headers={**headers, "x-probe-tag": tag},
    )


@pytest.mark.usefixtures("interleaved_authentication")
async def test_overlapping_requests_each_see_their_own_principal_session_and_policy(
    client, world: _World, points: _Checkpoints
) -> None:
    tags = [(name, copy) for name in world.principals for copy in range(2)]
    points.barriers = {
        point: asyncio.Barrier(len(tags))
        for point in ("auth_in", "auth_out", "after_auth", "after_policy")
    }

    responses = await asyncio.gather(
        *[
            _whoami(
                client,
                world.principals[name].headers[copy],
                f"{name}#{copy}",
                world.flow_id if name.startswith("A-") else None,
            )
            for name, copy in tags
        ]
    )

    bodies = []
    for (name, copy), response in zip(tags, responses, strict=True):
        assert response.status_code == 200, (name, response.text)
        body = response.json()
        principal = world.principals[name]
        assert body["tag"] == f"{name}#{copy}"
        if principal.user_id is not None:
            assert body["user"] == principal.user_id, body
        assert body["tenant"] == principal.tenant_id, body
        assert body["api_key"] is principal.api_key, body
        assert body["policy_user"] == body["user"], body
        assert body["db_email"] == body["email"], body
        assert body["policy_is_singleton"] and body["fresh_memo"], body
        assert body["memo_used"] is name.startswith("A-"), body
        assert body["policy_session"] and body["user_service_session"], body
        assert body["in_transaction"], body
        bodies.append(body)
    # All ten were alive together at the barriers, so equal ids would be one object.
    for key in ("container", "session", "policy"):
        assert len({body[key] for body in bodies}) == len(tags), key
    assert (
        len({body["user"] for body in bodies if body["tag"].startswith("A-editor")})
        == 1
    )


@pytest.mark.usefixtures("interleaved_authentication")
async def test_flow_reads_answer_alike_when_their_authentication_interleaves(
    client, world: _World, points: _Checkpoints
) -> None:
    # Each principal's two reads go out together, so each takes one credential.
    reads = [
        (name, route, url, credential)
        for name in world.principals
        for credential, (route, url) in enumerate(
            (
                ("status", f"{world.base}/runs/{world.run_id}/status/"),
                ("graph", f"{world.base}/graph/?run_id={world.run_id}"),
            )
        )
    ]
    one_by_one = {
        (name, route): (
            await client.get(url, headers=world.principals[name].headers[0])
        ).status_code
        for name, route, url, _credential in reads
    }

    points.barriers = {
        point: asyncio.Barrier(len(reads)) for point in ("auth_in", "auth_out")
    }
    responses = await asyncio.gather(
        *[
            client.get(url, headers=world.principals[name].headers[credential])
            for name, _route, url, credential in reads
        ]
    )

    assert {
        (name, route): response.status_code
        for (name, route, _url, _credential), response in zip(
            reads, responses, strict=True
        )
    } == one_by_one
    assert one_by_one == {
        ("A-admin-jwt", "status"): 200,
        ("A-admin-jwt", "graph"): 200,
        ("A-editor-jwt", "status"): 403,
        ("A-editor-jwt", "graph"): 403,
        ("A-admin-key", "status"): 200,
        ("A-admin-key", "graph"): 200,
        ("B-admin-jwt", "status"): 404,
        ("B-admin-jwt", "graph"): 404,
        ("B-admin-key", "status"): 403,
        ("B-admin-key", "graph"): 403,
    }


async def test_a_cancelled_request_returns_its_connection_and_the_next_is_clean(
    client, world: _World, points: _Checkpoints
) -> None:
    admin, admin_key = world.principals["A-admin-jwt"], world.principals["A-admin-key"]
    used = await _whoami(client, admin.headers[0], "used", world.flow_id)
    assert used.json()["memo_used"] is True, used.text
    pool = sessionmanager._engine.pool
    reached, never = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        reached.set()
        await never.wait()

    points.holds = {("after_policy", "cancelled"): hold}
    baseline = pool.checkedout()
    request = asyncio.create_task(_whoami(client, admin_key.headers[0], "cancelled"))
    await asyncio.wait_for(reached.wait(), 20)
    held = pool.checkedout()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request

    assert [baseline, held, pool.checkedout()] == [0, 1, 0]
    assert not points.seen["cancelled"]["session"].in_transaction()
    tenant_b = world.principals["B-admin-jwt"]
    after = await _whoami(client, tenant_b.headers[0], "after")
    assert after.status_code == 200, after.text
    body = after.json()
    assert (body["user"], body["tenant"]) == (tenant_b.user_id, tenant_b.tenant_id)
    assert body["fresh_memo"] and body["policy_user"] == body["user"], body


async def test_a_streaming_body_keeps_its_requests_session(
    client, admin_user, flow_process_auth_headers, points: _Checkpoints
) -> None:
    response = await client.get(
        "/api/v1/request-container-probe/stream/",
        headers=dict(flow_process_auth_headers),
    )

    assert response.status_code == 200, response.text
    assert response.text.splitlines() == [
        f"{chunk}:{admin_user.email}:True" for chunk in range(3)
    ]


async def test_a_function_scoped_write_is_visible_to_the_next_request(
    client, flow_process_auth_headers, points: _Checkpoints
) -> None:
    headers = dict(flow_process_auth_headers)

    written = await client.post(
        "/api/v1/request-container-probe/write/", headers=headers
    )
    me = await client.get("/api/v1/users/me/", headers=headers)

    assert written.status_code == 200, written.text
    assert me.json()["username"] == written.json()["username"]


async def test_a_sync_dependency_in_the_threadpool_copies_into_its_request(
    client, flow_process_auth_headers, points: _Checkpoints
) -> None:
    response = await client.get(
        "/api/v1/request-container-probe/threadpool/",
        headers=dict(flow_process_auth_headers),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"copied_off_the_loop": True, "request_session": True}


async def test_a_status_read_copies_no_more_providers_than_its_budget(
    client, world: _World, monkeypatch
) -> None:
    built: list[Container] = []

    def recording(**overriding_providers: providers.Provider[Any]) -> Container:
        built.append(request_container(**overriding_providers))
        return built[-1]

    monkeypatch.setattr(container_dependency, "request_container", recording)
    status = f"{world.base}/runs/{world.run_id}/status/"
    reached = {}
    for reader, principal in (
        ("tenant admin", world.principals["A-admin-jwt"]),
        ("admin api key", world.principals["A-admin-key"]),
    ):
        built.clear()
        response = await client.get(status, headers=principal.headers[0])
        assert response.status_code == 200, response.text
        [container] = built
        reached[reader] = sum(1 for _ in container.traverse())

    # A container that copied the whole graph, as Container does, fails the budget;
    # routing this read through a full Container fails the assertion below too.
    whole_graph = sum(1 for _ in Container(session=providers.Object(None)).traverse())
    assert _STATUS_COPY_CEILING < whole_graph
    assert all(count <= _STATUS_COPY_CEILING for count in reached.values()), (
        f"A status read reached {reached} providers (copies plus their override "
        f"Objects), ceiling {_STATUS_COPY_CEILING}"
    )
