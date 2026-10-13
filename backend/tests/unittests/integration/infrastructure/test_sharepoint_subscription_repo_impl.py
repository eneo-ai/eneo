"""The subscription insert survives losing the unique-constraint race."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.domain.repositories.sharepoint_subscription_repo import (
    SharePointSubscriptionExists,
)
from eneo.integration.infrastructure.mappers.sharepoint_subscription_mapper import (
    SharePointSubscriptionMapper,
)
from eneo.integration.infrastructure.sharepoint_subscription_repo_impl import (
    SharePointSubscriptionRepositoryImpl,
)


def _session(execute_side_effect):
    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute_side_effect)
    savepoints: list[str] = []

    @asynccontextmanager
    async def begin_nested():
        savepoints.append("begin")
        try:
            yield
        except BaseException:
            savepoints.append("rollback")
            raise
        savepoints.append("release")

    session.begin_nested = begin_nested
    return session, savepoints


def _subscription() -> SharePointSubscription:
    return SharePointSubscription(
        user_integration_id=uuid4(),
        site_id="site-1",
        subscription_id="sub-1",
        drive_id="drive-1",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )


class _DriverError(Exception):
    def __init__(self, message: str, constraint_name: str | None = None) -> None:
        super().__init__(message)
        self.constraint_name = constraint_name


@pytest.mark.parametrize(
    "driver_error",
    [
        pytest.param(
            Exception(
                'duplicate key value violates unique constraint "uq_sharepoint_subscription_user_site"'
            ),
            id="message",
        ),
        pytest.param(
            _DriverError("duplicate key", "uq_sharepoint_subscription_user_site"),
            id="constraint-name",
        ),
    ],
)
async def test_unique_violation_becomes_a_domain_error_inside_a_savepoint(
    driver_error,
):
    session, savepoints = _session(IntegrityError("INSERT", {}, driver_error))
    repo = SharePointSubscriptionRepositoryImpl(
        session=session, mapper=SharePointSubscriptionMapper()
    )
    subscription = _subscription()

    with pytest.raises(SharePointSubscriptionExists) as exc_info:
        await repo.add(subscription)

    assert exc_info.value.site_id == "site-1"
    assert savepoints == ["begin", "rollback"]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(RuntimeError("connection lost"), id="connection"),
        pytest.param(
            IntegrityError(
                "INSERT",
                {},
                _DriverError(
                    'insert or update on table "sharepoint_subscriptions" violates '
                    'foreign key constraint "fk_user_integration"',
                    "sharepoint_subscriptions_user_integration_id_fkey",
                ),
            ),
            id="foreign-key",
        ),
        pytest.param(
            IntegrityError("INSERT", {}, Exception('null value in column "site_id"')),
            id="not-null",
        ),
    ],
)
async def test_other_database_errors_propagate_unchanged(error):
    session, savepoints = _session(error)
    repo = SharePointSubscriptionRepositoryImpl(
        session=session, mapper=SharePointSubscriptionMapper()
    )

    with pytest.raises(type(error)):
        await repo.add(_subscription())
    assert savepoints == ["begin", "rollback"]


async def test_relinking_targets_only_unlinked_rows_of_the_same_resource():
    result = MagicMock(rowcount=2)
    session, _ = _session(None)
    session.execute = AsyncMock(return_value=result)
    repo = SharePointSubscriptionRepositoryImpl(
        session=session, mapper=SharePointSubscriptionMapper()
    )
    subscription = _subscription()
    subscription.id = uuid4()

    assert await repo.link_unreferenced_knowledge(subscription) == 2

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE integration_knowledge" in sql
    assert f"sharepoint_subscription_id='{subscription.id.hex}'" in sql
    assert "sharepoint_subscription_id IS NULL" in sql
    assert f"user_integration_id = '{subscription.user_integration_id.hex}'" in sql
    assert (
        "coalesce(integration_knowledge.site_id, integration_knowledge.drive_id) = 'site-1'"
        in sql
    )
