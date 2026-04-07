from typing import Annotated, NoReturn, cast
from uuid import UUID

from dependency_injector import providers

from fastapi import Depends, Request, Security, WebSocketException

from intric.authentication.api_key_router_helpers import raise_api_key_http_error
from intric.database.database import (
    AsyncSession,
    get_session,
    get_session_with_transaction,
    sessionmanager,
)
from intric.main.container.container import Container
from intric.main.container.container_overrides import override_user
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.server.dependencies.auth_definitions import (
    API_KEY_HEADER,
    OAUTH2_SCHEME,
    get_token_from_websocket_header,
)
from intric.users.setup import setup_user

def _raise_api_key_http_error(
    exc: ApiKeyValidationError,
    *,
    request: Request | None = None,
) -> NoReturn:
    raise_api_key_http_error(exc, request=request)


def get_container(
    with_user: bool = False,
    with_user_from_assistant_api_key: bool = False,
    with_transaction: bool = True,
):
    if sum([with_user, with_user_from_assistant_api_key]) > 1:
        raise ValueError(
            "Only one of with_user, with_user_from_assistant_api_key can be set to True"
        )

    async def _get_container(
        session: AsyncSession = Depends(
            get_session_with_transaction if with_transaction else get_session
        ),
    ):
        return Container(
            session=providers.Object(session),
        )

    async def _get_container_with_user(
        request: Request,
        token: str = Security(OAUTH2_SCHEME),
        api_key: str = Security(API_KEY_HEADER),
        container: Container = Depends(_get_container),
    ):
        if request.method == "OPTIONS":
            return container
        try:
            session = cast(AsyncSession, container.session())
            if session.in_transaction():
                user = await container.user_service().authenticate(
                    token=token, api_key=api_key, request=request
                )
            else:
                async with session.begin():
                    user = await container.user_service().authenticate(
                        token=token, api_key=api_key, request=request
                    )
        except ApiKeyValidationError as exc:
            _raise_api_key_http_error(exc, request=request)

        if not user.is_active:
            await setup_user(container=container, user=user)

        override_user(container=container, user=user)

        return container

    async def _get_container_with_user_from_assistant_api_key(
        id: UUID,
        request: Request,
        token: str = Security(OAUTH2_SCHEME),
        api_key: str = Security(API_KEY_HEADER),
        container: Container = Depends(_get_container),
    ):
        if request.method == "OPTIONS":
            return container
        try:
            session = cast(AsyncSession, container.session())
            if session.in_transaction():
                user = await container.user_service().authenticate_with_assistant_api_key(
                    token=token, api_key=api_key, assistant_id=id, request=request
                )
            else:
                async with session.begin():
                    user = (
                        await container.user_service().authenticate_with_assistant_api_key(
                            token=token, api_key=api_key, assistant_id=id, request=request
                        )
                    )
        except ApiKeyValidationError as exc:
            _raise_api_key_http_error(exc, request=request)
        override_user(container=container, user=user)

        return container

    if with_user:
        return _get_container_with_user

    if with_user_from_assistant_api_key:
        return _get_container_with_user_from_assistant_api_key

    return _get_container


def get_container_for_sysadmin():
    """Get a container for sysadmin endpoints that manage their own transactions.

    This function creates a container with a session that does NOT have a transaction
    already started. This allows worker tasks and services to manage their own
    transactions without running into "A transaction is already begun on this Session"
    errors.
    """

    async def _get_container_for_sysadmin(
        session: AsyncSession = Depends(get_session),
    ):
        return Container(
            session=providers.Object(session),
        )

    return _get_container_for_sysadmin


# TODO: Find a better place for this
async def get_user_from_websocket(
    token: Annotated[str, Security(get_token_from_websocket_header)],
    session: AsyncSession = Depends(get_session),
):
    async with sessionmanager.session() as session, session.begin():
        container = Container(session=providers.Object(session))

        try:
            user = await container.user_service().authenticate(token=token)
        except Exception as e:
            raise WebSocketException("Error connecting with websocket") from e

    return user
