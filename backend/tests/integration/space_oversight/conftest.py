"""People for the space oversight tests: the seeded tenant admin who creates
spaces, and a second tenant admin who oversees them without being a member."""

from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient

from eneo.roles.permissions import Permission
from tests.integration.space_oversight.support import (
    Person,
    new_person,
    seeded_admin,
)

MakePerson = Callable[..., Awaitable[Person]]


@pytest.fixture
def make_person(db_container, patch_auth_service_jwt) -> MakePerson:
    async def make(permissions: list[Permission], *, label: str = "person") -> Person:
        return await new_person(db_container, permissions, label=label)

    return make


@pytest.fixture
async def admin(db_container, patch_auth_service_jwt) -> Person:
    """The seeded tenant admin; creates the spaces, so is their admin."""
    return await seeded_admin(db_container)


@pytest.fixture
async def overseer(make_person: MakePerson) -> Person:
    """A tenant admin who is a member of no space and may mint API keys."""
    return await make_person([Permission.ADMIN, Permission.API_KEYS], label="overseer")


@pytest.fixture
async def raw_client(app) -> AsyncGenerator[AsyncClient, None]:
    """A client that turns unhandled server errors into 500 responses."""
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
    ) as client:
        yield client
