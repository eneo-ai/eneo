"""Account binding at each federated entry point, with PostgreSQL and Redis.

The generic callback (``POST /auth/callback``), the browser-session callback
(``GET /login/callback``) and the resource server (a provider's access token
as Bearer) take one admission decision: a bound identity reaches its account,
and an email binds only an account that has no binding yet. The provider is
tests/fake_oidc_provider.py, so every token is really signed and verified.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from eneo.audit.application import audit_service as audit_service_module
from eneo.audit.application.audit_worker_task import log_audit_event_task
from eneo.authentication import browser_session_service
from eneo.authentication import federation_router as federation_router_module
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.browser_sessions_table import BrowserSessions
from eneo.database.tables.identity_bindings_table import IdentityBindings
from eneo.database.tables.users_table import Users
from eneo.main.config import get_settings, set_settings
from eneo.main.logging import OTELJSONFormatter
from eneo.users import user_service as user_service_module
from eneo.users.identity_binding_repo import IdentityConflictError
from tests.fake_oidc_provider import FakeOidcProvider
from tests.integration.test_federation_tenant_admin import (
    SECRET,
    _idp,
    _register,
    _store,
    _stored,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

EMAIL = "test@example.com"
CLIENT = "operator-client"
API = "eneo-api"
SIGNED_IN = "signed_in"
ENTRY_POINTS = ["generic", "browser", "api"]


@pytest.fixture
def enqueued(monkeypatch) -> list[dict[str, Any]]:
    """Audit events sent to the worker; the queue itself is not running."""
    events: list[dict[str, Any]] = []

    async def enqueue(task, job_id, params):  # noqa: ARG001
        events.append(params)

    monkeypatch.setattr(audit_service_module.job_manager, "enqueue", enqueue)
    return events


@pytest.fixture
async def provider(
    client, super_admin_token, fake_idp, test_tenant
) -> AsyncIterator[FakeOidcProvider]:
    idp = _idp("binding")
    provider = fake_idp(
        issuer=idp["issuer"],
        client_id=CLIENT,
        client_secret=SECRET,
        other_clients={"client-b": SECRET},
        token_claims={"email": EMAIL},
    )
    await _register(
        client,
        super_admin_token,
        test_tenant.id,
        idp,
        canonical_public_origin="https://test.local",
    )
    # Browser sessions, as in production, and resource-server mode for the
    # same provider on its own API audience.
    current = get_settings()
    set_settings(
        current.model_copy(
            update={
                "browser_session_enabled": True,
                "environment": "production",
                "oidc_resource_server_enabled": True,
                "oidc_accepted_issuer": provider.issuer,
                "oidc_accepted_audience": API,
                "oidc_tenant_id": str(test_tenant.id),
            }
        )
    )
    try:
        yield provider
    finally:
        set_settings(current)


SignIn = Callable[..., Awaitable[str]]


@pytest.fixture
async def sign_in(
    client,
    patch_auth_service_jwt,
    mock_transcription_models,
    provider,
    db_container,
    test_tenant,
) -> SignIn:
    """Sign in through one entry point; returns ``SIGNED_IN`` or the typed
    refusal's code, after checking the refusal has that entry point's shape."""
    async with db_container() as container:
        slug = await container.tenant_repo().generate_slug_for_tenant(test_tenant.id)

    async def generic(**claims: Any) -> str:
        initiated = await client.get("/api/v1/auth/initiate", params={"tenant": slug})
        assert initiated.status_code == 200, initiated.text
        answer = provider.authorize(initiated.json()["authorization_url"], **claims)
        response = await client.post(
            "/api/v1/auth/callback",
            json={"code": answer.code, "state": initiated.json()["state"]},
        )
        if response.status_code == 200:
            return SIGNED_IN
        assert response.status_code == 403, response.text
        body = response.json()
        assert body["eneo_error_code"] == 9082
        assert "reason" not in json.dumps(body)
        return body["code"]

    async def browser(**claims: Any) -> str:
        initiated = await client.get(
            "/api/v1/auth/browser/initiate",
            params={"tenant": slug, "next": "/dashboard"},
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert initiated.status_code == 303, initiated.text
        location = initiated.headers["location"]
        [state] = parse_qs(urlsplit(location).query)["state"]
        answer = provider.authorize(location, **claims)
        [txn] = initiated.headers.get_list("set-cookie")
        response = await client.get(
            "/login/callback",
            params={"code": answer.code, "state": state},
            headers={"Cookie": txn.split(";", 1)[0], "Sec-Fetch-Site": "cross-site"},
        )
        assert response.status_code == 303, response.text
        target = urlsplit(response.headers["location"])
        if target.path == "/dashboard":
            return SIGNED_IN
        query = parse_qs(target.query)
        assert (target.path, query["message"]) == ("/login", ["oidc_callback_failed"])
        return query["detailCode"][0]

    async def api(client_id: str = CLIENT, **claims: Any) -> str:
        token = provider.access_token(
            audience=API, client_id=client_id, email=EMAIL, **claims
        )
        # The service, not GET /users/me/: a first request that binds writes,
        # and the safe-method tripwire is about cookies, which this is not.
        async with db_container() as container:
            try:
                await container.user_service().authenticate(token=token)
            except IdentityConflictError as exc:
                return exc.code
        return SIGNED_IN

    entry_points = {"generic": generic, "browser": browser, "api": api}

    async def _sign_in(entry: str, subject: str | None = None, **kwargs: Any) -> str:
        claims = {"sub": subject} if subject is not None else {}
        return await entry_points[entry](**claims, **kwargs)

    return _sign_in


def _audience(entry: str) -> str:
    return API if entry == "api" else CLIENT


async def _account() -> UUID:
    async with sessionmanager.session() as session, session.begin():
        found = await session.scalar(sa.select(Users.id).where(Users.email == EMAIL))
        assert found is not None
        return found


async def _bindings() -> set[tuple[UUID, str, str]]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.execute(
            sa.select(
                IdentityBindings.user_id,
                IdentityBindings.audience,
                IdentityBindings.subject,
            )
        )
        return set(rows.tuples())


async def _rows() -> dict[str, int]:
    """How many rows a sign-in may write: accounts, bindings, sessions."""
    async with sessionmanager.session() as session, session.begin():
        return {
            table.__tablename__: await session.scalar(
                sa.select(sa.func.count()).select_from(table)
            )
            for table in (Users, IdentityBindings, BrowserSessions)
        }


async def _bound_methods(user_id: UUID) -> list[str]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.scalars(
            sa.select(AuditLog)
            .where(AuditLog.action == "identity_bound", AuditLog.entity_id == user_id)
            .order_by(AuditLog.timestamp)
        )
        return [row.log_metadata["method"] for row in rows]


def _conflicts(enqueued: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in enqueued if event["action"] == "identity_conflict"]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
async def test_an_unbound_account_is_bound_by_its_email(sign_in, provider, entry):
    account = await _account()

    assert await sign_in(entry, "person-a") == SIGNED_IN
    assert await sign_in(entry, "person-a") == SIGNED_IN

    assert await _bindings() == {(account, _audience(entry), "person-a")}
    assert await _bound_methods(account) == ["email_match"]


@pytest.fixture
def conflict_logs() -> Iterator[list[str]]:
    """The identity_conflict log events as emitted: formatted while they are
    logged, so the request context of that moment is in them."""
    lines: list[str] = []
    formatter = OTELJSONFormatter()

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.getMessage() == "identity_conflict":
                lines.append(formatter.format(record))

    handler = Capture()
    user_service_module.logger.addHandler(handler)
    try:
        yield lines
    finally:
        user_service_module.logger.removeHandler(handler)


@pytest.mark.parametrize("entry", ENTRY_POINTS)
async def test_a_conflict_is_logged_without_the_email(
    sign_in, provider, conflict_logs, entry
):
    assert await sign_in(entry, "person-a") == SIGNED_IN

    assert await sign_in(entry, "someone-else") == "identity_conflict"

    [line] = conflict_logs
    assert json.loads(line)["attributes"]["reason"] == "subject_mismatch"
    assert EMAIL not in line


async def test_a_refused_callback_logs_no_email_with_oidc_diagnostics_on(
    sign_in, provider, monkeypatch
):
    # Diagnostics on: no event of the refused callback carries the address,
    # not only the conflict itself.
    assert await sign_in("generic", "person-a") == SIGNED_IN

    async def enabled(_redis_client: Any) -> bool:
        return True

    monkeypatch.setattr(federation_router_module, "is_debug_enabled", enabled)
    lines: list[str] = []
    formatter = OTELJSONFormatter()

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(formatter.format(record))

    handler = Capture(level=logging.DEBUG)
    loggers = (federation_router_module.logger, user_service_module.logger)
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    try:
        assert await sign_in("generic", "someone-else") == "identity_conflict"
    finally:
        for logger, level in zip(loggers, levels):
            logger.removeHandler(handler)
            logger.setLevel(level)

    assert any("callback.identity_conflict" in line for line in lines)
    assert not [line for line in lines if EMAIL in line]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
async def test_another_subject_under_the_bound_pair_is_refused_and_writes_nothing(
    sign_in, provider, enqueued, entry
):
    account = await _account()
    assert await sign_in(entry, "person-a") == SIGNED_IN
    before = await _rows()

    assert await sign_in(entry, "someone-else") == "identity_conflict"

    assert await _rows() == before
    assert await _bindings() == {(account, _audience(entry), "person-a")}
    [conflict] = _conflicts(enqueued)
    assert conflict["outcome"] == "failure"
    assert conflict["error_message"] == "subject_mismatch"
    assert conflict["metadata"] | {"correlation_id": None} == {
        "reason": "subject_mismatch",
        "issuer": provider.issuer,
        "audience": _audience(entry),
        "subject_claim": "sub",
        "subject": "someone-else",
        "account_ids": [str(account)],
        "correlation_id": None,
    }
    assert EMAIL not in json.dumps(conflict)


@pytest.mark.parametrize("entry", ENTRY_POINTS)
async def test_a_bound_account_takes_no_new_pair_by_email(
    sign_in, provider, enqueued, test_tenant, entry
):
    account = await _account()
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.insert(IdentityBindings).values(
                tenant_id=test_tenant.id,
                user_id=account,
                issuer=provider.issuer,
                audience="retired-client",
                subject_claim="sub",
                subject="person-old",
            )
        )

    assert await sign_in(entry, "person-new") == "identity_conflict"

    assert await _bindings() == {(account, "retired-client", "person-old")}
    assert [c["error_message"] for c in _conflicts(enqueued)] == ["account_bound"]


@pytest.mark.parametrize("change", ["pairwise", "pairwise-with-window", "one-subject"])
async def test_a_client_id_change_by_an_admin_needs_a_window_for_pairwise_subjects(
    client, sign_in, provider, enqueued, db_container, admin_user, change
):
    """The organisation admin's PATCH gives everyone a new pair. A provider
    that issues a subject per client presents a new subject there, so only a
    window from the old pair admits it; one subject for every client joins
    the account as the same subject."""
    provider.pairwise_subjects = change.startswith("pairwise")
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    admin = {"Authorization": f"Bearer {token}"}
    account = await _account()
    assert await sign_in("generic") == SIGNED_IN
    if change == "pairwise-with-window":
        opened = await client.post(
            "/api/v1/admin/identity-migration-windows",
            json={
                "from_issuer": provider.issuer,
                "from_audience": CLIENT,
                "to_issuer": provider.issuer,
                "to_audience": "client-b",
                "closes_at": (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
            },
            headers=admin,
        )
        assert opened.status_code == 201, opened.text

    view = await client.get("/api/v1/admin/federation", headers=admin)
    patched = await client.patch(
        "/api/v1/admin/federation",
        json={"revision": view.json()["revision"], "client_id": "client-b"},
        headers=admin,
    )
    assert patched.status_code == 200, patched.text
    before = await _rows()

    outcome = await sign_in("generic")

    old, new = provider.subject_for(CLIENT), provider.subject_for("client-b")
    if change == "pairwise":
        assert outcome == "identity_conflict"
        assert [c["error_message"] for c in _conflicts(enqueued)] == ["account_bound"]
        assert await _rows() == before
        assert await _bindings() == {(account, CLIENT, old)}
    else:
        assert outcome == SIGNED_IN
        assert await _bindings() == {(account, CLIENT, old), (account, "client-b", new)}
        assert (await _bound_methods(account))[-1] == (
            "migration_window" if change == "pairwise-with-window" else "same_subject"
        )


@pytest.mark.parametrize("queue", ["up", "down"])
async def test_a_recycled_email_after_a_client_change_is_refused_and_audited(
    sign_in, provider, enqueued, test_tenant, monkeypatch, queue
):
    account = await _account()
    assert await sign_in("generic", "person-a") == SIGNED_IN
    # The organisation moves to another client at the same provider; there
    # the address now belongs to someone else.
    await _store(
        test_tenant.id, {**await _stored(test_tenant.id), "client_id": "client-b"}
    )
    if queue == "down":

        async def unreachable(*args: Any) -> None:
            raise ConnectionError("queue unreachable")

        monkeypatch.setattr(audit_service_module.job_manager, "enqueue", unreachable)
    before = await _rows()

    # The refusal does not depend on the audit reaching the queue.
    assert await sign_in("generic", "someone-else") == "identity_conflict"

    assert await _rows() == before
    assert await _bindings() == {(account, CLIENT, "person-a")}
    if queue == "down":
        return
    # The sign-in rolled back; the worker still records the refusal.
    [conflict] = _conflicts(enqueued)
    async with sessionmanager.session() as session, session.begin():
        await log_audit_event_task(
            job_id=str(uuid4()), params=conflict, session=session
        )
    async with sessionmanager.session() as session, session.begin():
        [row] = await session.execute(
            sa.select(
                AuditLog.tenant_id,
                AuditLog.entity_id,
                AuditLog.actor_type,
                AuditLog.log_metadata,
            ).where(AuditLog.action == "identity_conflict")
        )
    tenant_id, entity_id, actor_type, metadata = row
    assert (tenant_id, entity_id, actor_type) == (test_tenant.id, account, "system")
    assert (metadata["reason"], metadata["audience"]) == ("account_bound", "client-b")


async def test_the_resource_server_answers_a_conflict_with_a_typed_403(
    client, sign_in, provider, enqueued
):
    assert await sign_in("api", "person-a") == SIGNED_IN
    token = provider.access_token(audience=API, client_id=CLIENT, email=EMAIL, sub="x")

    response = await client.get(
        "/api/v1/users/me/", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403, response.text
    body = response.json()
    assert (body["code"], body["eneo_error_code"]) == ("identity_conflict", 9082)


async def test_a_refusal_whose_audit_never_ends_keeps_the_typed_403(
    client, sign_in, provider, enqueued, monkeypatch
):
    # The refusal is audited through the queue during the admission, under
    # the store deadline. A queue that never answers ends the audit at the
    # deadline; the refusal it decided still answers.
    monkeypatch.setattr(browser_session_service, "STORE_DEADLINE_SECONDS", 0.5)
    assert await sign_in("api", "person-a") == SIGNED_IN
    token = provider.access_token(audience=API, client_id=CLIENT, email=EMAIL, sub="x")

    async def never(task, job_id, params):  # noqa: ARG001
        await asyncio.Event().wait()

    monkeypatch.setattr(audit_service_module.job_manager, "enqueue", never)
    async with asyncio.timeout(10):
        response = await client.get(
            "/api/v1/users/me/", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 403, response.text
    body = response.json()
    assert (body["code"], body["eneo_error_code"]) == ("identity_conflict", 9082)
    assert await _bindings() == {(await _account(), API, "person-a")}


@contextlib.contextmanager
def _binding_commit_fails() -> Iterator[None]:
    """The commit of a transaction that wrote an identity binding fails."""

    def recording(connection, cursor, statement, *args) -> None:  # noqa: ARG001
        if statement.startswith("INSERT INTO identity_bindings"):
            connection.info["wrote_binding"] = True

    def unavailable(connection) -> None:
        if connection.info.pop("wrote_binding", False):
            raise OperationalError("COMMIT", {}, ConnectionError("store unavailable"))

    event.listen(Engine, "before_cursor_execute", recording)
    event.listen(Engine, "commit", unavailable)
    try:
        yield
    finally:
        event.remove(Engine, "before_cursor_execute", recording)
        event.remove(Engine, "commit", unavailable)


async def test_a_resource_server_request_is_answered_only_once_its_binding_is_committed(
    raw_client, patch_auth_service_jwt, mock_transcription_models, provider, enqueued
):
    # A provider token's first request binds its identity. Answered before
    # the binding is durable, a failed commit would leave the identity
    # served as an account it does not hold, which a second identity could
    # then bind by the same email.
    token = provider.access_token(
        audience=API, client_id=CLIENT, email=EMAIL, sub="person-a"
    )
    personal_space = "/api/v1/spaces/type/personal/"
    bearer = {"Authorization": f"Bearer {token}"}

    with _binding_commit_fails():
        refused = await raw_client.get(personal_space, headers=bearer)

    assert refused.status_code == 500, refused.text
    assert await _bindings() == set()

    admitted = await raw_client.get(personal_space, headers=bearer)
    assert admitted.status_code == 200, admitted.text
    assert await _bindings() == {(await _account(), API, "person-a")}


async def test_a_binding_stays_when_the_request_that_made_it_fails(
    raw_client, patch_auth_service_jwt, mock_transcription_models, provider, enqueued
):
    # The binding belongs to the admission, not to the route: a route that
    # fails after authentication rolls back only its own work.
    token = provider.access_token(
        audience=API, client_id=CLIENT, email=EMAIL, sub="person-a"
    )

    missing = await raw_client.get(
        f"/api/v1/spaces/{uuid4()}/", headers={"Authorization": f"Bearer {token}"}
    )

    assert missing.status_code == 404, missing.text
    assert await _bindings() == {(await _account(), API, "person-a")}


async def test_an_admission_gives_up_on_an_account_locked_elsewhere(
    raw_client,
    patch_auth_service_jwt,
    mock_transcription_models,
    provider,
    enqueued,
    monkeypatch,
):
    # A first binding locks its account. While another transaction holds that
    # lock, the request fails within the store deadline instead of waiting.
    monkeypatch.setattr(browser_session_service, "STORE_DEADLINE_SECONDS", 1.0)
    token = provider.access_token(
        audience=API, client_id=CLIENT, email=EMAIL, sub="person-a"
    )
    account = await _account()

    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.select(Users.id).where(Users.id == account).with_for_update()
        )
        # Without a deadline the request would wait for this transaction,
        # which waits for the request.
        async with asyncio.timeout(10):
            refused = await raw_client.get(
                "/api/v1/spaces/type/personal/",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert refused.status_code == 500, refused.text
    assert await _bindings() == set()


@contextlib.contextmanager
def _connections_held() -> Iterator[dict[str, int]]:
    """The most database connections held at once while the block runs."""
    assert sessionmanager._engine is not None
    pool = sessionmanager._engine.sync_engine.pool
    held = {"now": 0, "most": 0}

    def checkout(*_args: Any) -> None:
        held["now"] += 1
        held["most"] = max(held["most"], held["now"])

    def checkin(*_args: Any) -> None:
        held["now"] -= 1

    event.listen(pool, "checkout", checkout)
    event.listen(pool, "checkin", checkin)
    try:
        yield held
    finally:
        event.remove(pool, "checkout", checkout)
        event.remove(pool, "checkin", checkin)


async def test_a_resource_server_request_holds_one_connection_at_a_time(
    client, patch_auth_service_jwt, mock_transcription_models, provider, enqueued
):
    # The admission takes a connection of its own. Creating an assistant
    # authenticates in a guard that then loads the space, and again in the
    # route's container: asking the pool for a second connection there,
    # while the request holds one, makes concurrent requests wait for each
    # other until the pool times out.
    token = provider.access_token(
        audience=API, client_id=CLIENT, email=EMAIL, sub="person-a"
    )
    bearer = {"Authorization": f"Bearer {token}"}

    with _connections_held() as binding:
        space = await client.get("/api/v1/spaces/type/personal/", headers=bearer)
    assert space.status_code == 200, space.text
    with _connections_held() as guarded:
        created = await client.post(
            f"/api/v1/spaces/{space.json()['id']}/applications/assistants/",
            json={"name": "Assistant"},
            headers=bearer,
        )
    assert created.status_code == 201, created.text

    assert (binding["most"], guarded["most"]) == (1, 1)


@pytest.mark.parametrize("first, second", [("browser", "api"), ("api", "browser")])
async def test_a_stable_id_claim_binds_one_account_across_audiences(
    sign_in, provider, test_tenant, first, second
):
    """A provider with a different ``sub`` per client names the person in a
    stable claim; mapped as the subject, it binds every audience."""
    provider.pairwise_subjects = True
    stored = await _stored(test_tenant.id)
    await _store(
        test_tenant.id,
        {**stored, "claims_mapping": {"email": "email", "subject": "oid"}},
    )
    account = await _account()

    # The API token comes from another client, with another ``sub``.
    clients: dict[str, dict[str, str]] = {
        "browser": {},
        "api": {"client_id": "mobile-app"},
    }
    assert await sign_in(first, **clients[first]) == SIGNED_IN
    assert await sign_in(second, **clients[second]) == SIGNED_IN

    assert await _bindings() == {
        (account, CLIENT, "person-0001"),
        (account, API, "person-0001"),
    }
    assert await _bound_methods(account) == ["email_match", "same_subject"]


async def test_pairwise_subjects_under_the_default_claim_bind_each_client_apart(
    sign_in, provider, enqueued
):
    """Under ``sub`` each client is another subject: an API token issued to
    the signing-in client is the same person, one issued to another client
    is not, and the API audience keeps one subject."""
    provider.pairwise_subjects = True
    account = await _account()

    assert await sign_in("browser") == SIGNED_IN
    assert await sign_in("api", client_id=CLIENT) == SIGNED_IN
    assert await sign_in("api", client_id="mobile-app") == "identity_conflict"

    assert await _bindings() == {
        (account, CLIENT, provider.subject_for(CLIENT)),
        (account, API, provider.subject_for(CLIENT)),
    }
    assert [c["error_message"] for c in _conflicts(enqueued)] == ["subject_mismatch"]
