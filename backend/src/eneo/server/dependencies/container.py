from typing import Annotated, Awaitable, Callable, NoReturn, cast
from uuid import UUID

from dependency_injector import providers
from fastapi import Depends, Request, Security, WebSocketException
from starlette.status import WS_1008_POLICY_VIOLATION

from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.api_key_router_helpers import raise_api_key_http_error
from eneo.database.database import (
    AsyncSession,
    get_session,
    get_session_with_transaction,
    sessionmanager,
)
from eneo.main.container.container import Container
from eneo.main.container.container_overrides import override_user
from eneo.object_content.deployment_policy import (
    UploadAdmissionSnapshot,
    load_upload_admission_snapshot,
)
from eneo.object_content.runtime import object_content_runtime
from eneo.server.dependencies.auth_definitions import (
    API_KEY_HEADER,
    OAUTH2_SCHEME,
    get_token_from_websocket_header,
)
from eneo.users.setup import setup_user
from eneo.users.user import UserInDB


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
    with_upload_admission: bool = False,
) -> Callable[..., Awaitable[Container]]:
    if sum([with_user, with_user_from_assistant_api_key]) > 1:
        raise ValueError(
            "Only one of with_user, with_user_from_assistant_api_key can be set to True"
        )
    if with_upload_admission and not with_user:
        raise ValueError("Upload admission requires an authenticated user container")

    async def _get_container(
        session: Annotated[
            AsyncSession,
            Depends(get_session_with_transaction if with_transaction else get_session),
        ],
    ) -> Container:
        return Container(
            session=providers.Object(session),
        )

    async def _get_container_with_user(
        request: Request,
        token: Annotated[str, Security(OAUTH2_SCHEME)],
        api_key: Annotated[str, Security(API_KEY_HEADER)],
        container: Annotated[Container, Depends(_get_container)],
    ) -> Container:
        if request.method == "OPTIONS":
            return container

        async def authenticate_and_prepare_container() -> UserInDB:
            user = await container.user_service().authenticate(
                token=token, api_key=api_key, request=request
            )
            if not user.is_active:
                await setup_user(container=container, user=user)
            if with_upload_admission:
                await load_container_upload_admission(container)
            return user

        try:
            session = cast(AsyncSession, container.session())
            if session.in_transaction():
                user = await authenticate_and_prepare_container()
            else:
                async with session.begin():
                    user = await authenticate_and_prepare_container()
        except ApiKeyValidationError as exc:
            _raise_api_key_http_error(exc, request=request)

        override_user(container=container, user=user)

        return container

    async def _get_container_with_user_from_assistant_api_key(
        id: UUID,
        request: Request,
        token: Annotated[str, Security(OAUTH2_SCHEME)],
        api_key: Annotated[str, Security(API_KEY_HEADER)],
        container: Annotated[Container, Depends(_get_container)],
    ) -> Container:
        if request.method == "OPTIONS":
            return container
        try:
            session = cast(AsyncSession, container.session())
            if session.in_transaction():
                user = (
                    await container.user_service().authenticate_with_assistant_api_key(
                        token=token, api_key=api_key, assistant_id=id, request=request
                    )
                )
            else:
                async with session.begin():
                    user = await container.user_service().authenticate_with_assistant_api_key(
                        token=token, api_key=api_key, assistant_id=id, request=request
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


async def load_container_upload_admission(
    container: Container,
) -> UploadAdmissionSnapshot:
    session = cast(AsyncSession, container.session())
    snapshot = await load_upload_admission_snapshot(
        session,
        inline_maximum_bytes=object_content_runtime.inline_maximum_bytes,
    )
    container.upload_admission.override(  # pyright: ignore[reportUnknownMemberType]
        providers.Object(snapshot)
    )
    return snapshot


def get_container_for_sysadmin() -> Callable[..., Awaitable[Container]]:
    """Get a container for sysadmin endpoints that manage their own transactions.

    This function creates a container with a session that does NOT have a transaction
    already started. This allows worker tasks and services to manage their own
    transactions without running into "A transaction is already begun on this Session"
    errors.
    """

    async def _get_container_for_sysadmin(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> Container:
        return Container(
            session=providers.Object(session),
        )

    return _get_container_for_sysadmin


# TODO: Find a better place for this
async def get_user_from_websocket(
    token: Annotated[str, Security(get_token_from_websocket_header)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserInDB:
    async with sessionmanager.session() as session, session.begin():
        container = Container(session=providers.Object(session))

        try:
            user = await container.user_service().authenticate(token=token)
        except Exception as e:
            raise WebSocketException(
                code=WS_1008_POLICY_VIOLATION,
                reason="Error connecting with websocket",
            ) from e

    return user
