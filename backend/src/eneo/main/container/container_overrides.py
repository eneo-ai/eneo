from dependency_injector import providers

from eneo.main.container.container import Container
from eneo.users.user import UserInDB


def override_user(container: Container, user: UserInDB):
    container.user.override(providers.Object(user))  # pyright: ignore[reportUnknownMemberType]  # dependency_injector Provider stubs are untyped
    container.tenant.override(providers.Object(user.tenant))  # pyright: ignore[reportUnknownMemberType]  # dependency_injector Provider stubs are untyped

    return container
