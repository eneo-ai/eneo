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
from eneo.main.container.container import Container
from eneo.main.container.request_container import request_container
from eneo.main.models import ModelId
from eneo.questions.questions_repo import QuestionRepository
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.server.dependencies import container as container_dependency
from eneo.server.dependencies.container import get_container
from eneo.users.user import UserAdd, UserState
from eneo.users.user_service import UserService
from tests.fixtures import mint_v2_api_key

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# Providers a /users/me read reaches, JWT or API key: the copies it touched
# and every provider they reach, override Objects included, at the measured
# count. Lower it when wiring shrinks; raise it only with the reason.
_ME_COPY_CEILING = 25

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
    # Seconds every request waits at each point, for routes that authenticate
    # a varying number of times and so cannot meet at a barrier.
    pause: float = 0.0

    async def reach(self, point: str, tag: str = "") -> None:
        if self.pause:
            await asyncio.sleep(self.pause)
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
    ) -> dict[str, object]:
        tag = request.headers["x-probe-tag"]
        await points.reach("after_auth", tag)
        service = container.space_service()
        singleton = container.tenant_app_auth_service()
        session = container.session()
        points.seen[tag] = {"container": container, "session": session}
        await points.reach("after_service", tag)
        user, tenant = container.user(), container.tenant()
        loaded = await container.user_repo().get_user_by_id_and_tenant_id(
            id=user.id, tenant_id=tenant.id
        )
        return {
            "tag": tag,
            "container": id(container),
            "session": id(session),
            "service": id(service),
            "singleton": id(singleton),
            "user": str(user.id),
            "email": user.email,
            "tenant": str(tenant.id),
            "api_key": user.active_api_key is not None,
            "service_user": str(service.user.id),
            "singleton_is_one": container.tenant_app_auth_service() is singleton,
            "service_session": service.repo.session is session,
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


def _bearer(container: Container, user) -> Headers:
    token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


@dataclass(frozen=True)
class _Principal:
    """Two credentials for one principal: one per concurrent request, since
    a key's row is updated when it is used."""

    headers: tuple[Headers, Headers]
    user_id: str
    tenant_id: str
    api_key: bool


@pytest.fixture
async def principals(
    client, db_container, admin_user, super_admin_token, patch_auth_service_jwt
) -> dict[str, _Principal]:
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
        jwt_a, jwt_b = _bearer(container, admin_user), _bearer(container, user_b)
        keys_a = await _two_keys(container, admin_user.tenant_id, admin_user.id)
        keys_b = await _two_keys(container, tenant_b_id, user_b.id)
    tenant_a, admin_id = str(admin_user.tenant_id), str(admin_user.id)
    user_b_id, tenant_b_str = str(user_b.id), str(tenant_b_id)
    return {
        "A-admin-jwt": _Principal((jwt_a, jwt_a), admin_id, tenant_a, False),
        "A-admin-key": _Principal(keys_a, admin_id, tenant_a, True),
        "B-admin-jwt": _Principal((jwt_b, jwt_b), user_b_id, tenant_b_str, False),
        "B-admin-key": _Principal(keys_b, user_b_id, tenant_b_str, True),
    }


async def _whoami(client, headers: Headers, tag: str):
    return await client.get(
        "/api/v1/request-container-probe/whoami/",
        headers={**headers, "x-probe-tag": tag},
    )


@pytest.mark.usefixtures("interleaved_authentication")
async def test_overlapping_requests_each_see_their_own_principal_session_and_services(
    client, principals: dict[str, _Principal], points: _Checkpoints
) -> None:
    tags = [(name, copy) for name in principals for copy in range(2)]
    points.barriers = {
        point: asyncio.Barrier(len(tags))
        for point in ("auth_in", "auth_out", "after_auth", "after_service")
    }

    responses = await asyncio.gather(
        *[
            _whoami(client, principals[name].headers[copy], f"{name}#{copy}")
            for name, copy in tags
        ]
    )

    bodies = []
    for (name, copy), response in zip(tags, responses, strict=True):
        assert response.status_code == 200, (name, response.text)
        body = response.json()
        principal = principals[name]
        assert body["tag"] == f"{name}#{copy}"
        assert body["user"] == principal.user_id, body
        assert body["tenant"] == principal.tenant_id, body
        assert body["api_key"] is principal.api_key, body
        assert body["service_user"] == body["user"], body
        assert body["db_email"] == body["email"], body
        assert body["singleton_is_one"], body
        assert body["service_session"] and body["user_service_session"], body
        assert body["in_transaction"], body
        bodies.append(body)
    # All eight were alive together at the barriers, so equal ids would be one object.
    for key in ("container", "session", "service", "singleton"):
        assert len({body[key] for body in bodies}) == len(tags), key
    # Nothing a request overrode reached the class-level providers.
    assert Container.user.overridden == ()
    assert Container.tenant.overridden == ()


@pytest.mark.usefixtures("interleaved_authentication")
async def test_hot_reads_answer_alike_when_their_authentication_interleaves(
    client, principals: dict[str, _Principal], points: _Checkpoints
) -> None:
    routes = ("/api/v1/users/me/", "/api/v1/spaces/", "/api/v1/settings/")
    # Each principal's reads go out together, each on its own credential copy.
    reads = [
        (name, route, credential % 2)
        for name in principals
        for credential, route in enumerate(routes)
    ]

    def _answer(response) -> tuple[int, object]:
        body = response.json()
        if isinstance(body, dict):
            body.pop("request_id", None)
            # The user's most recently used key: each copy uses its own.
            body.pop("truncated_api_key", None)
        return response.status_code, body

    one_by_one = {
        (name, route): _answer(
            await client.get(route, headers=principals[name].headers[0])
        )
        for name, route, _credential in reads
    }

    points.pause = 0.02
    responses = await asyncio.gather(
        *[
            client.get(route, headers=principals[name].headers[credential])
            for name, route, credential in reads
        ]
    )

    assert {
        (name, route): _answer(response)
        for (name, route, _credential), response in zip(reads, responses, strict=True)
    } == one_by_one
    assert {key: status for key, (status, _body) in one_by_one.items()} == {
        (name, route): 200 for name, route, _credential in reads
    }
    me = {name: one_by_one[(name, routes[0])][1] for name in principals}
    assert {name: body["id"] for name, body in me.items()} == {
        name: principal.user_id for name, principal in principals.items()
    }


async def test_a_cancelled_request_returns_its_connection_and_the_next_is_clean(
    client, principals: dict[str, _Principal], points: _Checkpoints
) -> None:
    admin_key = principals["A-admin-key"]
    pool = sessionmanager._engine.pool
    reached, never = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        reached.set()
        await never.wait()

    points.holds = {("after_service", "cancelled"): hold}
    baseline = pool.checkedout()
    request = asyncio.create_task(_whoami(client, admin_key.headers[0], "cancelled"))
    await asyncio.wait_for(reached.wait(), 20)
    held = pool.checkedout()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request

    assert [baseline, held, pool.checkedout()] == [0, 1, 0]
    assert not points.seen["cancelled"]["session"].in_transaction()
    tenant_b = principals["B-admin-jwt"]
    after = await _whoami(client, tenant_b.headers[0], "after")
    assert after.status_code == 200, after.text
    body = after.json()
    assert (body["user"], body["tenant"]) == (tenant_b.user_id, tenant_b.tenant_id)
    assert body["service_user"] == body["user"], body


async def test_a_streaming_body_keeps_its_requests_session(
    client, admin_user, principals: dict[str, _Principal], points: _Checkpoints
) -> None:
    response = await client.get(
        "/api/v1/request-container-probe/stream/",
        headers=principals["A-admin-jwt"].headers[0],
    )

    assert response.status_code == 200, response.text
    assert response.text.splitlines() == [
        f"{chunk}:{admin_user.email}:True" for chunk in range(3)
    ]


async def test_a_function_scoped_write_is_visible_to_the_next_request(
    client, principals: dict[str, _Principal], points: _Checkpoints
) -> None:
    headers = principals["A-admin-jwt"].headers[0]

    written = await client.post(
        "/api/v1/request-container-probe/write/", headers=headers
    )
    me = await client.get("/api/v1/users/me/", headers=headers)

    assert written.status_code == 200, written.text
    assert me.json()["username"] == written.json()["username"]


async def test_a_sync_dependency_in_the_threadpool_copies_into_its_request(
    client, principals: dict[str, _Principal], points: _Checkpoints
) -> None:
    response = await client.get(
        "/api/v1/request-container-probe/threadpool/",
        headers=principals["A-admin-jwt"].headers[0],
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"copied_off_the_loop": True, "request_session": True}


async def test_a_users_me_read_copies_no_more_providers_than_its_budget(
    client, principals: dict[str, _Principal], monkeypatch
) -> None:
    built: list[Container] = []

    def recording(**overriding_providers: providers.Provider[Any]) -> Container:
        built.append(request_container(**overriding_providers))
        return built[-1]

    monkeypatch.setattr(container_dependency, "request_container", recording)
    reached = {}
    for reader in ("A-admin-jwt", "A-admin-key"):
        built.clear()
        response = await client.get(
            "/api/v1/users/me/", headers=principals[reader].headers[0]
        )
        assert response.status_code == 200, response.text
        reached[reader] = max(sum(1 for _ in each.traverse()) for each in built)

    # A container that copied the whole graph, as Container does, fails the budget.
    whole_graph = sum(1 for _ in Container(session=providers.Object(None)).traverse())
    assert _ME_COPY_CEILING < whole_graph
    assert all(count <= _ME_COPY_CEILING for count in reached.values()), (
        f"A /users/me read reached {reached} providers (copies plus their override "
        f"Objects), ceiling {_ME_COPY_CEILING}"
    )
