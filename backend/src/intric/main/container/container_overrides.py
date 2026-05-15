from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from typing import TypeVar, cast

from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from intric.main.container.container import Container
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB

_T = TypeVar("_T")


def _override_provider(
    provider: providers.Provider[_T],
    value: _T,
) -> AbstractContextManager[object]:
    return cast(
        AbstractContextManager[object],
        provider.override(providers.Object(value)),  # pyright: ignore[reportUnknownMemberType]  # dependency_injector Provider stubs do not type override contexts
    )


def override_user(container: Container, user: UserInDB) -> Container:
    # Legacy sysadmin flows expect dependency-injector's immediate override side effect.
    _override_provider(container.user, user)
    _override_provider(container.tenant, user.tenant)

    return container


@contextmanager
def scoped_container_overrides(
    container: Container,
    *,
    user: UserInDB | None = None,
    tenant: TenantInDB | None = None,
    session: AsyncSession | None = None,
) -> Iterator[Container]:
    scoped_tenant = tenant if tenant is not None else user.tenant if user else None

    with ExitStack() as stack:
        if user is not None:
            stack.enter_context(_override_provider(container.user, user))
        if scoped_tenant is not None:
            stack.enter_context(_override_provider(container.tenant, scoped_tenant))
        if session is not None:
            stack.enter_context(_override_provider(container.session, session))

        yield container
