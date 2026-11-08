"""Which account a verified identity reaches, decided against PostgreSQL.

``UserService.resolve_federated_user`` is the one admission decision of every
federated entry point (tests/integration/test_identity_binding_sign_in.py
drives them over HTTP). Here it runs on real sessions, so the unique keys and
the account row lock decide the races, as they do in production.
"""

import asyncio
from collections.abc import Awaitable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

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
from eneo.main.exceptions import FederatedLoginDenied
from eneo.users.identity_binding_repo import IdentityConflictError
from eneo.users.user import UserInDB, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ISSUER = "https://idp.binding.local"
EMAIL = "test@example.com"
REMOVED = "inactive or has been removed"


@pytest.fixture(autouse=True)
def enqueued(monkeypatch) -> list[dict[str, Any]]:
    """Audit events sent to the worker; the queue itself is not running."""
    events: list[dict[str, Any]] = []

    async def enqueue(task, job_id, params):  # noqa: ARG001
        events.append(params)

    monkeypatch.setattr(audit_service_module.job_manager, "enqueue", enqueue)
    return events


@pytest.fixture
def sign_in(db_container, test_tenant):
    """Admit an identity in its own transaction, committed on success."""

    async def _sign_in(
        subject: str,
        audience: str = "client-a",
        *,
        email: str = EMAIL,
        issuer: str = ISSUER,
        subject_claim: str = "sub",
    ) -> UserInDB:
        identity = FederatedIdentity(
            issuer=issuer,
            audience=audience,
            subject_claim=subject_claim,
            subject=subject,
            email=email,
            email_verified=True,
        )
        async with db_container() as container:
            user, _ = await container.user_service().resolve_federated_user(
                identity=identity,
                tenant_id=test_tenant.id,
                allowed_domains=["example.com"],
                correlation_id="binding-test",
            )
            return user

    return _sign_in


async def _execute(statement: Any) -> Any:
    async with sessionmanager.session() as session, session.begin():
        return await session.execute(statement)


async def _user_id(email: str = EMAIL) -> UUID:
    async with sessionmanager.session() as session, session.begin():
        found = await session.scalar(
            sa.select(Users.id).where(Users.email == email, Users.deleted_at.is_(None))
        )
        assert found is not None
        return found


async def _add_user(tenant_id: UUID, email: str) -> UUID:
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(
            sa.insert(Users)
            .values(
                email=email,
                username=f"user-{uuid4().hex[:8]}",
                tenant_id=tenant_id,
                state=UserState.ACTIVE.value,
            )
            .returning(Users.id)
        )


async def _bind(tenant_id: UUID, user_id: UUID, subject: str, audience: str) -> None:
    await _execute(
        sa.insert(IdentityBindings).values(
            tenant_id=tenant_id,
            user_id=user_id,
            issuer=ISSUER,
            audience=audience,
            subject_claim="sub",
            subject=subject,
        )
    )


async def _bindings(user_id: UUID | None = None) -> set[tuple[str, str]]:
    """(audience, subject) of every binding, or of one account's."""
    query = sa.select(IdentityBindings.audience, IdentityBindings.subject)
    if user_id is not None:
        query = query.where(IdentityBindings.user_id == user_id)
    async with sessionmanager.session() as session, session.begin():
        return set((await session.execute(query)).tuples())


async def _claimed_bindings() -> set[tuple[UUID, str, str]]:
    """(account, subject claim, subject) of every binding."""
    query = sa.select(
        IdentityBindings.user_id,
        IdentityBindings.subject_claim,
        IdentityBindings.subject,
    )
    async with sessionmanager.session() as session, session.begin():
        return set((await session.execute(query)).tuples())


async def _bound_audits(user_id: UUID) -> list[dict[str, Any]]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.scalars(
            sa.select(AuditLog)
            .where(AuditLog.action == "identity_bound", AuditLog.entity_id == user_id)
            .order_by(AuditLog.timestamp)
        )
        return [row.log_metadata for row in rows]


def _conflicts(enqueued: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event["metadata"]
        for event in enqueued
        if event["action"] == "identity_conflict"
    ]


async def _set_state(user_id: UUID, state: UserState, *, removed: bool) -> None:
    await _execute(
        sa.update(Users)
        .where(Users.id == user_id)
        .values(
            state=state.value,
            deleted_at=datetime.now(timezone.utc) if removed else None,
        )
    )


async def _allow_rebinding(user_id: UUID, until: timedelta) -> None:
    await _execute(
        sa.update(Users)
        .where(Users.id == user_id)
        .values(identity_rebinding_until=datetime.now(timezone.utc) + until)
    )


async def _rebinding_until(user_id: UUID) -> datetime | None:
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(
            sa.select(Users.identity_rebinding_until).where(Users.id == user_id)
        )


async def _open_window(
    tenant_id: UUID, from_audience: str, to_audience: str, closes_in: timedelta
) -> UUID:
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(
            sa.insert(IdentityMigrationWindows)
            .values(
                tenant_id=tenant_id,
                from_issuer=ISSUER,
                from_audience=from_audience,
                to_issuer=ISSUER,
                to_audience=to_audience,
                closes_at=datetime.now(timezone.utc) + closes_in,
            )
            .returning(IdentityMigrationWindows.id)
        )


async def test_the_first_sign_in_binds_by_email_and_later_ones_need_no_email(
    sign_in, enqueued
):
    account = await _user_id()

    first = await sign_in("person-a")
    # The provider changed the person's address: the binding still decides.
    renamed = await sign_in("person-a", email="renamed@example.com")

    assert first.id == renamed.id == account
    assert await _bindings(account) == {("client-a", "person-a")}
    [bound] = await _bound_audits(account)
    assert bound["method"] == "email_match"
    assert (bound["issuer"], bound["audience"], bound["subject"]) == (
        ISSUER,
        "client-a",
        "person-a",
    )
    assert _conflicts(enqueued) == []


async def test_another_subject_under_the_bound_pair_is_refused(sign_in, enqueued):
    account = await _user_id()
    await sign_in("person-a")

    with pytest.raises(IdentityConflictError):
        await sign_in("someone-else")

    assert await _bindings() == {("client-a", "person-a")}
    [conflict] = _conflicts(enqueued)
    assert conflict["reason"] == "subject_mismatch"
    assert conflict["subject"] == "someone-else"
    assert conflict["account_ids"] == [str(account)]


async def test_a_new_pair_for_a_bound_account_needs_a_window_or_an_allowance(
    sign_in, enqueued
):
    await sign_in("person-a")

    with pytest.raises(IdentityConflictError):
        await sign_in("person-b", "client-b")

    assert await _bindings() == {("client-a", "person-a")}
    assert [c["reason"] for c in _conflicts(enqueued)] == ["account_bound"]


async def test_a_removed_account_keeps_its_identity_reserved(sign_in, test_tenant):
    account = await _user_id()
    await sign_in("person-a")
    await _set_state(account, UserState.DELETED, removed=True)
    # Someone else now has the address, with an allowance to re-bind.
    newcomer = await _add_user(test_tenant.id, EMAIL)
    await _allow_rebinding(newcomer, timedelta(days=1))

    with pytest.raises(FederatedLoginDenied, match=REMOVED):
        await sign_in("person-a")
    # The same subject under another audience is the same person.
    with pytest.raises(FederatedLoginDenied, match=REMOVED):
        await sign_in("person-a", "eneo-api")

    assert await _bindings(newcomer) == set()
    assert await _rebinding_until(newcomer) is not None
    # SCIM reactivation reuses the row, so its identity comes back with it.
    await _set_state(newcomer, UserState.DELETED, removed=True)
    await _set_state(account, UserState.ACTIVE, removed=False)
    assert (await sign_in("person-a")).id == account


async def test_an_inactive_bound_account_is_refused(sign_in):
    account = await _user_id()
    await sign_in("person-a")
    await _set_state(account, UserState.INACTIVE, removed=False)

    with pytest.raises(FederatedLoginDenied, match=REMOVED):
        await sign_in("person-a")


async def test_the_same_subject_under_another_audience_binds_without_email(sign_in):
    account = await _user_id()
    await sign_in("person-a")

    api = await sign_in("person-a", "eneo-api", email="unknown@example.com")

    assert api.id == account
    assert await _bindings(account) == {
        ("client-a", "person-a"),
        ("eneo-api", "person-a"),
    }
    assert [b["method"] for b in await _bound_audits(account)] == [
        "email_match",
        "same_subject",
    ]


async def test_the_same_subject_keeps_the_rule_of_one_subject_per_pair(
    sign_in, test_tenant, enqueued
):
    account = await _user_id()
    await _bind(test_tenant.id, account, "person-a", "client-a")
    await _bind(test_tenant.id, account, "api-subject", "eneo-api")

    with pytest.raises(IdentityConflictError):
        await sign_in("person-a", "eneo-api")

    assert [c["reason"] for c in _conflicts(enqueued)] == ["subject_mismatch"]


async def test_a_subject_bound_to_two_accounts_is_refused(
    sign_in, test_tenant, enqueued
):
    first = await _user_id()
    second = await _add_user(test_tenant.id, "second@example.com")
    await _bind(test_tenant.id, first, "person-a", "client-a")
    await _bind(test_tenant.id, second, "person-a", "client-b")

    with pytest.raises(IdentityConflictError):
        await sign_in("person-a", "eneo-api")

    [conflict] = _conflicts(enqueued)
    assert conflict["reason"] == "duplicate_subject"
    assert sorted(conflict["account_ids"]) == sorted([str(first), str(second)])


async def test_case_variants_of_one_address_are_refused(sign_in, test_tenant, enqueued):
    await _add_user(test_tenant.id, "Dup@Example.com")
    await _add_user(test_tenant.id, "dup@example.com")

    with pytest.raises(IdentityConflictError):
        await sign_in("person-d", email="dup@example.com")

    assert await _bindings() == set()
    [conflict] = _conflicts(enqueued)
    assert conflict["reason"] == "duplicate_email"
    assert len(conflict["account_ids"]) == 2


async def test_an_open_migration_window_adds_the_new_pair(
    sign_in, test_tenant, enqueued
):
    account = await _user_id()
    await sign_in("person-a")
    window = await _open_window(
        test_tenant.id, "client-a", "client-b", timedelta(days=1)
    )

    assert (await sign_in("person-b", "client-b")).id == account

    # Add, not move: the old pair still signs in.
    assert (await sign_in("person-a")).id == account
    assert await _bindings(account) == {
        ("client-a", "person-a"),
        ("client-b", "person-b"),
    }
    bound = (await _bound_audits(account))[-1]
    assert (bound["method"], bound["window_id"]) == ("migration_window", str(window))
    assert _conflicts(enqueued) == []


@pytest.mark.parametrize(
    "from_audience, closes_in",
    [("client-a", timedelta(seconds=-1)), ("client-x", timedelta(days=1))],
    ids=["closed", "from-another-pair"],
)
async def test_a_window_that_is_closed_or_from_another_pair_binds_nothing(
    sign_in, test_tenant, enqueued, from_audience, closes_in
):
    await sign_in("person-a")
    await _open_window(test_tenant.id, from_audience, "client-b", closes_in)

    with pytest.raises(IdentityConflictError):
        await sign_in("person-b", "client-b")

    assert await _bindings() == {("client-a", "person-a")}
    assert [c["reason"] for c in _conflicts(enqueued)] == ["account_bound"]


async def test_a_window_to_the_same_pair_replaces_the_subject_once(
    sign_in, test_tenant, enqueued
):
    """The provider now names people by another claim: every subject under
    the pair changes, and the window moves each account to its new one."""
    account = await _user_id()
    await sign_in("person-a")
    window = await _open_window(
        test_tenant.id, "client-a", "client-a", timedelta(days=1)
    )

    assert (await sign_in("person-b")).id == account

    assert await _bindings(account) == {("client-a", "person-b")}
    bound = (await _bound_audits(account))[-1]
    assert {
        key: bound[key]
        for key in ("method", "window_id", "subject", "replaced_subject")
    } == {
        "method": "migration_window",
        "window_id": str(window),
        "subject": "person-b",
        "replaced_subject": "person-a",
    }
    # Once per account: the replaced binding is newer than the window.
    with pytest.raises(IdentityConflictError):
        await sign_in("person-c")
    assert await _bindings(account) == {("client-a", "person-b")}
    assert [c["reason"] for c in _conflicts(enqueued)] == ["subject_mismatch"]


async def test_same_pair_windows_move_every_audience_of_a_changed_subject_claim(
    sign_in, test_tenant
):
    """A person bound under the browser client and the API audience: after the
    subject claim changes, the second audience finds the account by its new
    subject under the browser pair, not by email, and its window still moves
    it."""
    account = await _user_id()
    await sign_in("person-a", "client-a")
    await sign_in("person-a", "api-a")
    windows = {
        audience: await _open_window(
            test_tenant.id, audience, audience, timedelta(days=1)
        )
        for audience in ("client-a", "api-a")
    }

    assert (await sign_in("person-b", "client-a")).id == account
    assert (await sign_in("person-b", "api-a")).id == account

    assert await _bindings(account) == {("client-a", "person-b"), ("api-a", "person-b")}
    moved = {
        audit["audience"]: audit
        for audit in await _bound_audits(account)
        if audit["method"] == "migration_window"
    }
    assert {
        audience: (audit["window_id"], audit["replaced_subject"])
        for audience, audit in moved.items()
    } == {
        "client-a": (str(windows["client-a"]), "person-a"),
        "api-a": (str(windows["api-a"]), "person-a"),
    }


async def test_a_pair_without_its_own_same_pair_window_is_refused(
    sign_in, test_tenant, enqueued
):
    account = await _user_id()
    await sign_in("person-a", "client-a")
    await sign_in("person-a", "api-a")
    await _open_window(test_tenant.id, "client-a", "client-a", timedelta(days=1))

    assert (await sign_in("person-b", "client-a")).id == account
    with pytest.raises(IdentityConflictError):
        await sign_in("person-b", "api-a")

    assert await _bindings(account) == {("client-a", "person-b"), ("api-a", "person-a")}
    assert [c["reason"] for c in _conflicts(enqueued)] == ["subject_mismatch"]


@pytest.mark.parametrize("window", [False, True], ids=["no-window", "same-pair-window"])
async def test_a_new_subject_claim_never_signs_one_person_in_to_another(
    sign_in, test_tenant, enqueued, window
):
    """Under the old claim A is "x" and B is "y"; the new claim gives each the
    other's value. A binding names its claim, so B's new "x" is not A's old
    one: each reaches their own account through the email, and only a window
    replaces their binding."""
    a = await _user_id()
    b = await _add_user(test_tenant.id, "b@example.com")
    await sign_in("x")
    await sign_in("y", email="b@example.com")
    if window:
        await _open_window(test_tenant.id, "client-a", "client-a", timedelta(days=1))

    reached: list[UUID | str] = []
    for subject, email in (("x", "b@example.com"), ("y", EMAIL)):
        try:
            user = await sign_in(subject, email=email, subject_claim="oid")
            reached.append(user.id)
        except IdentityConflictError as refused:
            reached.append(refused.reason)

    if window:
        assert reached == [b, a]
        assert await _claimed_bindings() == {(b, "oid", "x"), (a, "oid", "y")}
        moved = (await _bound_audits(b))[-1]
        assert (moved["subject_claim"], moved["replaced_subject_claim"]) == (
            "oid",
            "sub",
        )
    else:
        assert reached == ["subject_mismatch", "subject_mismatch"]
        assert await _claimed_bindings() == {(a, "sub", "x"), (b, "sub", "y")}
        assert {c["subject_claim"] for c in _conflicts(enqueued)} == {"oid"}


@pytest.mark.parametrize("closed", ["closed", "expired"])
async def test_a_same_pair_window_no_longer_open_replaces_nothing(
    sign_in, test_tenant, enqueued, closed
):
    await sign_in("person-a")
    window = await _open_window(
        test_tenant.id,
        "client-a",
        "client-a",
        timedelta(days=1) if closed == "closed" else timedelta(seconds=-1),
    )
    if closed == "closed":
        await _execute(
            sa.update(IdentityMigrationWindows)
            .where(IdentityMigrationWindows.id == window)
            .values(closes_at=sa.func.now())
        )

    with pytest.raises(IdentityConflictError):
        await sign_in("person-b")

    assert await _bindings() == {("client-a", "person-a")}
    assert [c["reason"] for c in _conflicts(enqueued)] == ["subject_mismatch"]


async def test_a_same_pair_window_never_takes_another_accounts_identity(
    sign_in, test_tenant
):
    account = await _user_id()
    holder = await _add_user(test_tenant.id, "holder@example.com")
    await sign_in("person-a")
    await _bind(test_tenant.id, holder, "person-h", "client-a")
    await _open_window(test_tenant.id, "client-a", "client-a", timedelta(days=1))

    # The presented identity is bound: it reaches its holder, whatever the email.
    assert (await sign_in("person-h")).id == holder

    assert await _bindings(account) == {("client-a", "person-a")}
    assert await _bindings(holder) == {("client-a", "person-h")}


async def test_a_same_pair_window_loses_a_key_taken_while_it_waited(
    sign_in, test_tenant, enqueued
):
    account = await _user_id()
    holder = await _add_user(test_tenant.id, "holder@example.com")
    await sign_in("person-a")
    await _open_window(test_tenant.id, "client-a", "client-a", timedelta(days=1))

    # The account's lock is held while another account takes the new key.
    async with sessionmanager.session() as session, session.begin():
        await session.execute(_lock(account))
        waiting = asyncio.ensure_future(sign_in("person-b"))
        await _wait_for_lock_waiters(1)
        await session.execute(
            sa.insert(IdentityBindings).values(
                tenant_id=test_tenant.id,
                user_id=holder,
                issuer=ISSUER,
                audience="client-a",
                subject_claim="sub",
                subject="person-b",
            )
        )
    with pytest.raises(IdentityConflictError) as refused:
        await waiting

    assert refused.value.reason == "identity_taken"
    assert await _bindings(account) == {("client-a", "person-a")}
    assert [c["account_ids"] for c in _conflicts(enqueued)] == [
        [str(account), str(holder)]
    ]


async def test_a_rebinding_allowance_replaces_the_subject_once(sign_in, enqueued):
    account = await _user_id()
    await sign_in("person-a")
    await _allow_rebinding(account, timedelta(days=1))

    assert (await sign_in("person-b")).id == account

    assert await _bindings(account) == {("client-a", "person-b")}
    assert await _rebinding_until(account) is None
    bound = (await _bound_audits(account))[-1]
    assert (bound["method"], bound["replaced_subject"]) == (
        "admin_allowance",
        "person-a",
    )
    with pytest.raises(IdentityConflictError):
        await sign_in("person-c")
    assert [c["reason"] for c in _conflicts(enqueued)] == ["subject_mismatch"]


async def test_a_rebinding_allowance_also_admits_a_new_pair(sign_in):
    account = await _user_id()
    await sign_in("person-a")
    await _allow_rebinding(account, timedelta(days=1))

    await sign_in("person-b", "client-b")

    assert await _bindings(account) == {
        ("client-a", "person-a"),
        ("client-b", "person-b"),
    }
    assert await _rebinding_until(account) is None


async def test_an_expired_allowance_binds_nothing(sign_in):
    await sign_in("person-a")
    await _allow_rebinding(await _user_id(), timedelta(seconds=-1))

    with pytest.raises(IdentityConflictError):
        await sign_in("person-b")


async def test_an_allowance_never_takes_an_identity_another_account_holds(
    sign_in, test_tenant
):
    account = await _user_id()
    holder = await _add_user(test_tenant.id, "holder@example.com")
    await _bind(test_tenant.id, holder, "person-h", "client-a")
    await _allow_rebinding(account, timedelta(days=1))

    assert (await sign_in("person-h")).id == holder

    assert await _bindings(account) == set()
    assert await _rebinding_until(account) is not None


async def _wait_for_lock_waiters(count: int) -> None:
    async with asyncio.timeout(10):
        while True:
            async with sessionmanager.session() as session, session.begin():
                waiting = await session.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock'"
                    )
                )
            if waiting >= count:
                return
            await asyncio.sleep(0.02)


async def _wait_for_waiters_on(session: Any) -> None:
    """Until a backend waits for a lock this session holds."""
    pid = await session.scalar(sa.text("SELECT pg_backend_pid()"))
    async with asyncio.timeout(10):
        while True:
            async with sessionmanager.session() as probe, probe.begin():
                waiting = await probe.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE :pid = ANY(pg_blocking_pids(pid))"
                    ),
                    {"pid": pid},
                )
            if waiting:
                return
            await asyncio.sleep(0.02)


async def _race(statement: Any, *sign_ins: Awaitable[UserInDB]) -> list[Any]:
    """Start the sign-ins while ``statement`` holds its row lock; commit it
    once they all wait on that lock."""
    tasks: list[asyncio.Future[UserInDB]] = []
    try:
        async with sessionmanager.session() as session, session.begin():
            await session.execute(statement)
            tasks = [asyncio.ensure_future(sign_in) for sign_in in sign_ins]
            await _wait_for_lock_waiters(len(tasks))
    finally:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return results


def _lock(user_id: UUID) -> Any:
    return sa.select(Users.id).where(Users.id == user_id).with_for_update()


async def test_one_identity_signing_in_twice_at_once_gets_one_binding(sign_in):
    account = await _user_id()

    results = await _race(_lock(account), sign_in("person-a"), sign_in("person-a"))

    assert [user.id for user in results] == [account, account]
    assert await _bindings() == {("client-a", "person-a")}
    assert len(await _bound_audits(account)) == 1


async def test_two_subjects_for_one_unbound_account_at_once_admit_one(
    sign_in, enqueued
):
    account = await _user_id()

    results = await _race(_lock(account), sign_in("person-a"), sign_in("someone-else"))

    admitted = [r for r in results if isinstance(r, UserInDB)]
    refused = [r for r in results if isinstance(r, IdentityConflictError)]
    assert [user.id for user in admitted] == [account]
    assert len(refused) == 1
    assert len(await _bindings(account)) == 1
    assert [c["reason"] for c in _conflicts(enqueued)] == ["subject_mismatch"]


async def test_one_subject_signing_in_under_two_audiences_at_once_binds_one_account(
    sign_in, test_tenant
):
    """Both first sign-ins see the subject unbound, and their emails name two
    accounts. The later one must see the earlier one's binding and join its
    account as the same subject, as it would one after the other."""
    first = await _user_id()
    second = await _add_user(test_tenant.id, "second@example.com")
    both = sa.select(Users.id).where(Users.id.in_([first, second])).with_for_update()

    results = await _race(
        both,
        sign_in("person-a", "client-a"),
        sign_in("person-a", "api-a", email="second@example.com"),
    )

    owners = {account for account, _, _ in await _claimed_bindings()}
    assert len(owners) == 1, owners
    assert [getattr(result, "id", result) for result in results] == [*owners] * 2
    assert await _bindings(*owners) == {("client-a", "person-a"), ("api-a", "person-a")}


def _retire(account: UUID, subject: str) -> Any:
    """What a re-binding by window or allowance commits: the account's
    subject replaced under its pair."""
    return (
        sa.update(IdentityBindings)
        .where(IdentityBindings.user_id == account)
        .values(subject=subject)
    )


async def test_a_subject_retired_during_the_lock_wait_is_not_added_again(
    sign_in, enqueued
):
    account = await _user_id()
    await sign_in("person-a", "client-a")

    async with sessionmanager.session() as session, session.begin():
        await session.execute(_lock(account))
        waiting = asyncio.ensure_future(sign_in("person-a", "api-a"))
        await _wait_for_lock_waiters(1)
        await session.execute(_retire(account, "person-b"))
    # Decided again: the email finds the account, now bound under another pair.
    with pytest.raises(IdentityConflictError) as refused:
        await waiting

    assert refused.value.reason == "account_bound"
    assert await _bindings(account) == {("client-a", "person-b")}


async def test_an_email_changed_during_the_lock_wait_binds_nothing(sign_in):
    account = await _user_id()

    async with sessionmanager.session() as session, session.begin():
        await session.execute(_lock(account))
        waiting = asyncio.ensure_future(sign_in("person-a"))
        await _wait_for_lock_waiters(1)
        await session.execute(
            sa.update(Users)
            .where(Users.id == account)
            .values(email="renamed@example.com")
        )
    with pytest.raises(FederatedLoginDenied, match="User not found"):
        await waiting

    assert await _bindings() == set()


async def test_an_account_that_changes_again_during_the_second_wait_is_refused(
    sign_in, test_tenant, enqueued
):
    first = await _user_id()
    second = await _add_user(test_tenant.id, "second@example.com")
    await sign_in("person-a", "client-a")

    async with sessionmanager.session() as hold_second, hold_second.begin():
        await hold_second.execute(_lock(second))
        async with sessionmanager.session() as hold_first, hold_first.begin():
            await hold_first.execute(_lock(first))
            waiting = asyncio.ensure_future(
                sign_in("person-a", "api-a", email="second@example.com")
            )
            await _wait_for_lock_waiters(1)
            await hold_first.execute(_retire(first, "person-b"))
        # Decided again, by the email: now it waits for the second account.
        await _wait_for_waiters_on(hold_second)
        await hold_second.execute(
            sa.update(Users)
            .where(Users.id == second)
            .values(email="renamed@example.com")
        )
    with pytest.raises(IdentityConflictError) as refused:
        await waiting

    assert refused.value.reason == "account_changed"
    assert await _bindings(first) == {("client-a", "person-b")}
    assert await _bindings(second) == set()
    assert [c["account_ids"] for c in _conflicts(enqueued)] == [[str(second)]]


@pytest.mark.parametrize(
    "state, removed",
    [(UserState.DELETED, True), (UserState.INACTIVE, False)],
    ids=["scim-active-false", "admin-deactivation"],
)
async def test_a_deactivation_committed_during_the_lock_wait_refuses(
    sign_in, state, removed
):
    account = await _user_id()
    deactivate = (
        sa.update(Users)
        .where(Users.id == account)
        .values(
            state=state.value,
            deleted_at=datetime.now(timezone.utc) if removed else None,
        )
    )

    [result] = await _race(deactivate, sign_in("person-a"))

    assert isinstance(result, FederatedLoginDenied)
    assert REMOVED in str(result)
    assert await _bindings() == set()


async def test_a_new_account_losing_its_insert_to_scim_binds_the_scim_account(
    sign_in, test_tenant
):
    await _execute(
        sa.update(Tenants).where(Tenants.id == test_tenant.id).values(provisioning=True)
    )
    scim_create = (
        sa.insert(Users)
        .values(
            email="new@example.com",
            username="scim-new",
            tenant_id=test_tenant.id,
            state=UserState.ACTIVE.value,
        )
        .returning(Users.id)
    )

    [result] = await _race(scim_create, sign_in("person-n", email="new@example.com"))

    assert isinstance(result, UserInDB), result
    async with sessionmanager.session() as session, session.begin():
        accounts = list(
            await session.scalars(
                sa.select(Users.id).where(Users.email == "new@example.com")
            )
        )
    assert accounts == [result.id]
    assert await _bindings(result.id) == {("client-a", "person-n")}
    assert [b["method"] for b in await _bound_audits(result.id)] == ["email_match"]
