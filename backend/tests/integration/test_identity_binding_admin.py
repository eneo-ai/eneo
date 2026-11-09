"""An org admin re-opens email matching on purpose: for one account
(``/api/v1/admin/users/{user_id}/identity``) or for every account bound under
one provider pair (``/api/v1/admin/identity-migration-windows``). Both end on
their own, at most 30 days ahead, and every change is audited."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.audit.application import audit_service as audit_service_module
from eneo.authentication.auth_models import FederatedIdentity
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.identity_bindings_table import (
    IdentityBindings,
    IdentityMigrationWindows,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.users.identity_binding_repo import IdentityConflictError
from eneo.users.user import UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ISSUER = "https://idp.binding.local"
WINDOWS = "/api/v1/admin/identity-migration-windows"


@pytest.fixture(autouse=True)
def enqueued(monkeypatch) -> list[dict[str, Any]]:
    """Conflict audits sent to the worker; the queue itself is not running."""
    events: list[dict[str, Any]] = []

    async def enqueue(task, job_id, params):  # noqa: ARG001
        events.append(params)

    monkeypatch.setattr(audit_service_module.job_manager, "enqueue", enqueue)
    return events


@pytest.fixture
async def admin(db_container, patch_auth_service_jwt, admin_user) -> dict[str, str]:
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sign_in(db_container, test_tenant):
    """Admit an identity in its own transaction, committed on success."""

    async def _sign_in(email: str, subject: str, audience: str = "client-a") -> UUID:
        async with db_container() as container:
            user, _ = await container.user_service().resolve_federated_user(
                identity=FederatedIdentity(
                    issuer=ISSUER,
                    audience=audience,
                    subject=subject,
                    email=email,
                    email_verified=True,
                ),
                tenant_id=test_tenant.id,
                allowed_domains=["example.com"],
                correlation_id="binding-admin-test",
            )
            return user.id

    return _sign_in


async def _person(
    tenant_id: UUID, name: str, *, email: str | None = None
) -> tuple[UUID, str]:
    """A bindable account named ``name``: its id and its email."""
    email = email or f"{name}@example.com"
    async with sessionmanager.session() as session, session.begin():
        account = await session.scalar(
            sa.insert(Users)
            .values(
                email=email,
                username=name,
                tenant_id=tenant_id,
                state=UserState.ACTIVE.value,
            )
            .returning(Users.id)
        )
    assert account is not None
    return account, email


def _identity_url(account: UUID) -> str:
    return f"/api/v1/admin/users/{account}/identity"


def _rebinding_url(account: UUID) -> str:
    return f"{_identity_url(account)}/rebinding"


async def _rebinding_until(account: UUID) -> datetime | None:
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(
            sa.select(Users.identity_rebinding_until).where(Users.id == account)
        )


def _ahead(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


async def _subjects(email: str) -> set[tuple[str, str]]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.execute(
            sa.select(IdentityBindings.audience, IdentityBindings.subject)
            .join(Users, Users.id == IdentityBindings.user_id)
            .where(Users.email == email)
        )
        return set(rows.tuples())


async def _audits(action: str) -> list[dict[str, Any]]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.execute(
            sa.select(
                AuditLog.actor_id,
                AuditLog.entity_type,
                AuditLog.entity_id,
                AuditLog.log_metadata,
            )
            .where(AuditLog.action == action)
            .order_by(AuditLog.timestamp)
        )
        return [
            {
                "actor_id": actor_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "metadata": metadata,
            }
            for actor_id, entity_type, entity_id, metadata in rows
        ]


async def _refusal(sign_in_call: Any) -> str:
    with pytest.raises(IdentityConflictError) as refused:
        await sign_in_call
    return refused.value.reason


async def test_the_identity_view_shows_the_bindings_and_the_allowance(
    client: AsyncClient, admin, sign_in, test_tenant
):
    account_id, email = await _person(test_tenant.id, "anna")
    await sign_in(email, "anna-1")

    response = await client.get(_identity_url(account_id), headers=admin)

    assert response.status_code == 200, response.text
    body = response.json()
    [binding] = body["bindings"]
    assert {
        k: binding[k] for k in ("issuer", "audience", "subject_claim", "subject")
    } == {
        "issuer": ISSUER,
        "audience": "client-a",
        "subject_claim": "sub",
        "subject": "anna-1",
    }
    assert binding["created_at"]
    assert body["rebinding_allowed_until"] is None


async def test_an_allowance_admits_one_new_subject_and_is_then_cleared(
    client: AsyncClient, admin, admin_user, sign_in, test_tenant
):
    account_id, email = await _person(test_tenant.id, "anna")
    account = await sign_in(email, "anna-1")
    until = _ahead(timedelta(days=1))

    response = await client.put(
        _rebinding_url(account_id), json={"allowed_until": until}, headers=admin
    )

    assert response.status_code == 200, response.text
    allowed = datetime.fromisoformat(response.json()["rebinding_allowed_until"])
    assert allowed == datetime.fromisoformat(until)
    # The provider re-issued the person under a new subject.
    assert await sign_in(email, "anna-2") == account
    view = (await client.get(_identity_url(account_id), headers=admin)).json()
    assert [b["subject"] for b in view["bindings"]] == ["anna-2"]
    assert view["rebinding_allowed_until"] is None
    # Single use: the next new subject is refused again.
    assert await _refusal(sign_in(email, "anna-3")) == "subject_mismatch"

    [audit] = await _audits("identity_rebinding_updated")
    assert (audit["actor_id"], audit["entity_type"], audit["entity_id"]) == (
        admin_user.id,
        "user",
        account,
    )
    change = audit["metadata"]["changes"]["rebinding_allowed_until"]
    assert change["old"] is None
    assert datetime.fromisoformat(change["new"]) == datetime.fromisoformat(until)


async def test_a_withdrawn_allowance_admits_nothing(
    client: AsyncClient, admin, sign_in, test_tenant
):
    account_id, email = await _person(test_tenant.id, "anna")
    await sign_in(email, "anna-1")
    await client.put(
        _rebinding_url(account_id),
        json={"allowed_until": _ahead(timedelta(days=1))},
        headers=admin,
    )

    response = await client.delete(_rebinding_url(account_id), headers=admin)

    assert response.status_code == 200, response.text
    assert response.json()["rebinding_allowed_until"] is None
    assert await _refusal(sign_in(email, "anna-2")) == "subject_mismatch"
    assert await _subjects(email) == {("client-a", "anna-1")}
    opened, withdrawn = await _audits("identity_rebinding_updated")
    assert opened["metadata"]["changes"]["rebinding_allowed_until"]["new"]
    assert withdrawn["metadata"]["changes"]["rebinding_allowed_until"]["new"] is None


@pytest.mark.parametrize(
    "until",
    [
        pytest.param(_ahead(timedelta(minutes=-1)), id="past"),
        pytest.param(_ahead(timedelta(days=30, hours=1)), id="beyond-30-days"),
        pytest.param("2030-01-01T00:00:00", id="no-time-zone"),
    ],
)
async def test_an_allowance_and_a_window_end_within_30_days(
    client: AsyncClient, admin, sign_in, test_tenant, until
):
    account_id, email = await _person(test_tenant.id, "anna")
    await sign_in(email, "anna-1")
    window = {
        "from_issuer": ISSUER,
        "from_audience": "client-a",
        "to_issuer": ISSUER,
        "to_audience": "client-b",
        "closes_at": until,
    }

    allowance = await client.put(
        _rebinding_url(account_id), json={"allowed_until": until}, headers=admin
    )
    opened = await client.post(WINDOWS, json=window, headers=admin)

    assert (allowance.status_code, opened.status_code) == (422, 422)
    assert (await client.get(WINDOWS, headers=admin)).json() == []
    view = (await client.get(_identity_url(account_id), headers=admin)).json()
    assert view["rebinding_allowed_until"] is None
    assert await _audits("identity_rebinding_updated") == []
    assert await _audits("identity_migration_window_updated") == []


async def test_a_window_adds_the_new_pair_until_it_is_closed(
    client: AsyncClient, admin, admin_user, sign_in, test_tenant
):
    _, anna = await _person(test_tenant.id, "anna")
    _, bo = await _person(test_tenant.id, "bo")
    await sign_in(anna, "anna-a")
    await sign_in(bo, "bo-a")
    closes_at = _ahead(timedelta(days=7))

    opened = await client.post(
        WINDOWS,
        json={
            "from_issuer": ISSUER,
            "from_audience": "client-a",
            "to_issuer": ISSUER,
            "to_audience": "client-b",
            "closes_at": closes_at,
        },
        headers=admin,
    )

    assert opened.status_code == 201, opened.text
    window = opened.json()
    assert (await client.get(WINDOWS, headers=admin)).json() == [window]
    await sign_in(anna, "anna-b", audience="client-b")
    # Add, not move: the first pair still signs in.
    assert await _subjects(anna) == {("client-a", "anna-a"), ("client-b", "anna-b")}

    closed = await client.delete(f"{WINDOWS}/{window['id']}", headers=admin)

    assert closed.status_code == 200, closed.text
    assert datetime.fromisoformat(closed.json()["closes_at"]) <= datetime.now(
        timezone.utc
    )
    assert (await client.get(WINDOWS, headers=admin)).json() == []
    assert await _refusal(sign_in(bo, "bo-b", audience="client-b")) == "account_bound"
    assert await _subjects(bo) == {("client-a", "bo-a")}
    again = await client.delete(f"{WINDOWS}/{window['id']}", headers=admin)
    assert again.status_code == 404

    audits = await _audits("identity_migration_window_updated")
    assert [a["metadata"]["extra"]["change"] for a in audits] == ["opened", "closed"]
    for audit in audits:
        assert (audit["actor_id"], audit["entity_type"], audit["entity_id"]) == (
            admin_user.id,
            "federation_config",
            test_tenant.id,
        )
        assert audit["metadata"]["extra"]["window_id"] == window["id"]
        assert audit["metadata"]["extra"]["to_audience"] == "client-b"


async def test_an_expired_window_is_not_listed_and_admits_nobody(
    client: AsyncClient, admin, sign_in, test_tenant
):
    _, anna = await _person(test_tenant.id, "anna")
    await sign_in(anna, "anna-a")
    opened = await client.post(
        WINDOWS,
        json={
            "from_issuer": ISSUER,
            "from_audience": "client-a",
            "to_issuer": ISSUER,
            "to_audience": "client-b",
            "closes_at": _ahead(timedelta(days=1)),
        },
        headers=admin,
    )
    window_id = opened.json()["id"]
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(IdentityMigrationWindows)
            .where(IdentityMigrationWindows.id == window_id)
            .values(closes_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )

    assert (await client.get(WINDOWS, headers=admin)).json() == []
    assert (
        await _refusal(sign_in(anna, "anna-b", audience="client-b")) == "account_bound"
    )
    response = await client.delete(f"{WINDOWS}/{window_id}", headers=admin)
    assert response.status_code == 404


async def test_a_window_may_lead_to_its_own_pair(
    client: AsyncClient, admin, admin_user, sign_in, test_tenant
):
    """For a change of subject claim: the issuer and audience stay, every
    subject under them changes."""
    _, anna = await _person(test_tenant.id, "anna")
    account = await sign_in(anna, "anna-sub")

    response = await client.post(
        WINDOWS,
        json={
            "from_issuer": ISSUER,
            "from_audience": "client-a",
            "to_issuer": ISSUER,
            "to_audience": "client-a",
            "closes_at": _ahead(timedelta(days=1)),
        },
        headers=admin,
    )

    assert response.status_code == 201, response.text
    assert await sign_in(anna, "anna-stable-id") == account
    assert await _subjects(anna) == {("client-a", "anna-stable-id")}
    [audit] = await _audits("identity_migration_window_updated")
    assert audit["actor_id"] == admin_user.id


async def test_an_unknown_account_has_no_identity(client: AsyncClient, admin):
    account_id = uuid4()

    view = await client.get(_identity_url(account_id), headers=admin)
    allowance = await client.put(
        _rebinding_url(account_id),
        json={"allowed_until": _ahead(timedelta(days=1))},
        headers=admin,
    )
    withdrawal = await client.delete(_rebinding_url(account_id), headers=admin)

    assert [r.status_code for r in (view, allowance, withdrawal)] == [404] * 3


async def test_the_routes_act_only_on_the_account_they_name(
    client: AsyncClient, admin, sign_in, test_tenant
):
    # Usernames are not unique: two accounts of one organisation can share
    # one, so the routes name the account by its id.
    first, first_email = await _person(test_tenant.id, "anna")
    second, second_email = await _person(
        test_tenant.id, "anna", email="anna.s@example.com"
    )
    await sign_in(first_email, "anna-1")
    await sign_in(second_email, "anna-2")
    allowance = {"allowed_until": _ahead(timedelta(days=1))}

    opened = await client.put(_rebinding_url(second), json=allowance, headers=admin)

    assert opened.status_code == 200, opened.text
    views = {
        account: (await client.get(_identity_url(account), headers=admin)).json()
        for account in (first, second)
    }
    assert [b["subject"] for b in views[first]["bindings"]] == ["anna-1"]
    assert views[first]["rebinding_allowed_until"] is None
    assert [b["subject"] for b in views[second]["bindings"]] == ["anna-2"]
    assert views[second]["rebinding_allowed_until"] is not None

    await client.put(_rebinding_url(first), json=allowance, headers=admin)
    withdrawn = await client.delete(_rebinding_url(second), headers=admin)

    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["rebinding_allowed_until"] is None
    assert await _rebinding_until(first) is not None
    assert await _rebinding_until(second) is None


async def test_an_account_of_another_organisation_is_not_found(
    client: AsyncClient, admin
):
    other = uuid4()
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.insert(Tenants).values(
                id=other,
                name=f"other-{other.hex[:8]}",
                quota_limit=1_000_000,
                state="active",
            )
        )
    account_id, _ = await _person(other, "anna")
    allowance = {"allowed_until": _ahead(timedelta(days=1))}

    answers = [
        await client.get(_identity_url(account_id), headers=admin),
        await client.put(_rebinding_url(account_id), json=allowance, headers=admin),
        await client.delete(_rebinding_url(account_id), headers=admin),
    ]

    assert [a.status_code for a in answers] == [404] * 3
    assert await _rebinding_until(account_id) is None


async def test_only_an_admin_in_an_interactive_session_reaches_them(
    client: AsyncClient,
    tenant_user_token: str,
    admin_user_api_key,
    sign_in,
    test_tenant,
):
    account_id, email = await _person(test_tenant.id, "anna")
    await sign_in(email, "anna-1")
    window = {
        "from_issuer": ISSUER,
        "from_audience": "client-a",
        "to_issuer": ISSUER,
        "to_audience": "client-b",
        "closes_at": _ahead(timedelta(days=1)),
    }
    allowance = {"allowed_until": _ahead(timedelta(days=1))}
    refused = {
        "anonymous": ({}, 401),
        "member": ({"Authorization": f"Bearer {tenant_user_token}"}, 403),
        "admin API key": ({"X-API-Key": admin_user_api_key.key}, 403),
    }

    for name, (headers, status) in refused.items():
        answers = [
            await client.get(_identity_url(account_id), headers=headers),
            await client.put(
                _rebinding_url(account_id), json=allowance, headers=headers
            ),
            await client.delete(_rebinding_url(account_id), headers=headers),
            await client.get(WINDOWS, headers=headers),
            await client.post(WINDOWS, json=window, headers=headers),
            await client.delete(f"{WINDOWS}/{uuid4()}", headers=headers),
        ]
        assert [a.status_code for a in answers] == [status] * 6, name
        if name == "admin API key":
            assert {a.json()["code"] for a in answers} == {"session_auth_required"}

    assert await _rebinding_until(account_id) is None
    async with sessionmanager.session() as session, session.begin():
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(IdentityMigrationWindows)
            )
            == 0
        )
