from typing import cast
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from intric.main.container.container import Container
from intric.main.container.container_overrides import (
    override_user,
    scoped_container_overrides,
)
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB


def _tenant(name: str) -> TenantInDB:
    return TenantInDB(
        id=uuid4(),
        name=name,
        quota_limit=0,
        quota_used=0,
    )


def _user(*, tenant: TenantInDB, username: str) -> UserInDB:
    return UserInDB(
        id=uuid4(),
        username=username,
        email=f"{username}@example.com",
        salt="salt",
        password="password",
        used_tokens=0,
        tenant_id=tenant.id,
        quota_used=0,
        tenant=tenant,
        state="active",
    )


def _session() -> AsyncSession:
    return cast(AsyncSession, create_autospec(AsyncSession, instance=True))


def test_scoped_container_overrides_restore_previous_values() -> None:
    original_tenant = _tenant("original")
    original_user = _user(tenant=original_tenant, username="original")
    original_session = _session()
    scoped_tenant = _tenant("scoped")
    scoped_user = _user(tenant=scoped_tenant, username="scoped")
    scoped_session = _session()
    container = Container(
        user=providers.Object(original_user),
        tenant=providers.Object(original_tenant),
        session=providers.Object(original_session),
    )

    with scoped_container_overrides(
        container,
        user=scoped_user,
        session=scoped_session,
    ):
        assert container.user() is scoped_user
        assert container.tenant() is scoped_tenant
        assert container.session() is scoped_session

    assert container.user() is original_user
    assert container.tenant() is original_tenant
    assert container.session() is original_session


def test_scoped_container_overrides_restore_after_exception() -> None:
    original_tenant = _tenant("original")
    original_user = _user(tenant=original_tenant, username="original")
    original_session = _session()
    scoped_tenant = _tenant("scoped")
    scoped_user = _user(tenant=scoped_tenant, username="scoped")
    container = Container(
        user=providers.Object(original_user),
        tenant=providers.Object(original_tenant),
        session=providers.Object(original_session),
    )

    with pytest.raises(RuntimeError, match="boom"):
        with scoped_container_overrides(container, user=scoped_user):
            assert container.user() is scoped_user
            assert container.tenant() is scoped_tenant
            raise RuntimeError("boom")

    assert container.user() is original_user
    assert container.tenant() is original_tenant
    assert container.session() is original_session


def test_scoped_container_overrides_tenant_only_keeps_other_providers() -> None:
    original_tenant = _tenant("original")
    original_user = _user(tenant=original_tenant, username="original")
    original_session = _session()
    scoped_tenant = _tenant("scoped")
    container = Container(
        user=providers.Object(original_user),
        tenant=providers.Object(original_tenant),
        session=providers.Object(original_session),
    )

    with scoped_container_overrides(container, tenant=scoped_tenant):
        assert container.user() is original_user
        assert container.tenant() is scoped_tenant
        assert container.session() is original_session

    assert container.user() is original_user
    assert container.tenant() is original_tenant
    assert container.session() is original_session


def test_scoped_container_overrides_session_only_keeps_other_providers() -> None:
    original_tenant = _tenant("original")
    original_user = _user(tenant=original_tenant, username="original")
    original_session = _session()
    scoped_session = _session()
    container = Container(
        user=providers.Object(original_user),
        tenant=providers.Object(original_tenant),
        session=providers.Object(original_session),
    )

    with scoped_container_overrides(container, session=scoped_session):
        assert container.user() is original_user
        assert container.tenant() is original_tenant
        assert container.session() is scoped_session

    assert container.user() is original_user
    assert container.tenant() is original_tenant
    assert container.session() is original_session


def test_scoped_container_overrides_explicit_tenant_wins_over_user_tenant() -> None:
    original_tenant = _tenant("original")
    original_user = _user(tenant=original_tenant, username="original")
    user_tenant = _tenant("user-tenant")
    explicit_tenant = _tenant("explicit")
    scoped_user = _user(tenant=user_tenant, username="scoped")
    original_session = _session()
    container = Container(
        user=providers.Object(original_user),
        tenant=providers.Object(original_tenant),
        session=providers.Object(original_session),
    )

    with scoped_container_overrides(
        container,
        user=scoped_user,
        tenant=explicit_tenant,
    ):
        assert container.user() is scoped_user
        assert container.tenant() is explicit_tenant
        assert container.session() is original_session

    assert container.user() is original_user
    assert container.tenant() is original_tenant
    assert container.session() is original_session


def test_override_user_keeps_legacy_immediate_override_behavior() -> None:
    original_tenant = _tenant("original")
    original_user = _user(tenant=original_tenant, username="original")
    new_tenant = _tenant("new")
    new_user = _user(tenant=new_tenant, username="new")
    container = Container(
        user=providers.Object(original_user),
        tenant=providers.Object(original_tenant),
        session=providers.Object(_session()),
    )

    returned_container = override_user(container, new_user)

    assert returned_container is container
    assert container.user() is new_user
    assert container.tenant() is new_tenant
