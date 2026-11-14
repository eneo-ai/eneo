"""Who is calling on the connector protocol's routes.

Two credentials, checked in this order:

1. The calling installation's: a shared key and an assertion it signed for
   exactly this request (``eneo.connector_protocol.verification``). The key
   says which installation, and so which tenant, the call is for. Anything
   wrong here is a 401, and nothing is answered to an unverified request.
2. The person's: an access token from the shared identity provider, issued for
   Eneo, admitted exactly as a bearer request's would be. Tenancy, spaces and
   permissions are then Eneo's own. What the installation says about the
   person (the ``actor``) never decides access.
"""

import time
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request

from eneo.authentication.endpoint_access import Authentication, authenticates
from eneo.connector_protocol import errors
from eneo.connector_protocol.installation import ConnectorInstallation
from eneo.connector_protocol.installation_keys import installation_keys
from eneo.connector_protocol.manifest import CONNECTOR_ID
from eneo.connector_protocol.verification import (
    Actor,
    Binding,
    body_digest,
    key_digest,
    key_matches,
    unverified_key_id,
    verify_assertion,
)
from eneo.database.database import AsyncSession
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.container.container_overrides import override_user
from eneo.main.exceptions import AuthenticationException, UnauthorizedException
from eneo.main.logging import get_logger
from eneo.server.dependencies.container import get_container
from eneo.server.dependencies.widget_auth import bearer_token
from eneo.users.setup import setup_user

logger = get_logger(__name__)

KEY_HEADER = "x-clew-connector-key"
DELEGATED_TOKEN_HEADER = "x-clew-delegated-token"

# No transaction of the request's own: the answer to a question is streamed
# after the route returns, as on the conversation routes.
_Container = Annotated[Container, Depends(get_container(with_transaction=False))]


@dataclass
class ConnectorCall:
    """A request the calling installation's credentials were verified for."""

    request: Request
    container: Container
    installation: ConnectorInstallation
    actor: Actor
    body: bytes

    async def as_person(self) -> Container:
        """The request's container, acting as the person the call is made for."""
        token = self.request.headers.get(DELEGATED_TOKEN_HEADER, "").strip()
        if not token:
            raise errors.person_missing()
        if not get_settings().oidc_resource_server_enabled:
            raise errors.unavailable(
                "Eneo är inte inställt för att ta emot inloggningar från andra system."
            )
        session = cast(AsyncSession, self.container.session())
        try:
            async with session.begin():
                user = await self.container.user_service().authenticate_delegated_token(
                    token, self.request
                )
                if not user.is_active:
                    await setup_user(container=self.container, user=user)
        except (AuthenticationException, UnauthorizedException, HTTPException) as exc:
            logger.info(
                "A delegated token was refused on a connector route",
                extra={"reason": type(exc).__name__},
            )
            raise errors.person_refused() from exc
        # The key chose the tenant; a person of another tenant has no business
        # behind it, whatever their token is good for elsewhere.
        if user.tenant_id != self.installation.tenant_id:
            raise errors.person_refused()
        override_user(container=self.container, user=user)
        return self.container


@authenticates(Authentication.CONNECTOR)
async def get_connector_call(request: Request, container: _Container) -> ConnectorCall:
    # Read once: the assertion is bound to these exact bytes.
    body = await request.body()
    key = request.headers.get(KEY_HEADER)
    assertion = bearer_token(request)
    kid = unverified_key_id(assertion) if assertion else None
    if not key or assertion is None or kid is None:
        raise errors.installation_refused()

    session = cast(AsyncSession, container.session())
    async with session.begin():
        installation = await container.connector_installation_repo().get_by_key_digest(
            key_digest(key)
        )
    if installation is None or not key_matches(key, installation.key_digest):
        raise errors.installation_refused()

    actor = verify_assertion(
        assertion,
        await installation_keys(installation.base_url, kid),
        CONNECTOR_ID,
        now=time.time(),
        binding=Binding(
            body=body_digest(body),
            # The capability route names one; every other route binds to none.
            capability=request.path_params.get("name"),
        ),
    )
    if actor is None:
        raise errors.installation_refused()
    return ConnectorCall(
        request=request,
        container=container,
        installation=installation,
        actor=actor,
        body=body,
    )


VerifiedCall = Annotated[ConnectorCall, Depends(get_connector_call)]
