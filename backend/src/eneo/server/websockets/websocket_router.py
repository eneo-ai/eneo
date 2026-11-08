import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from starlette.status import WS_1008_POLICY_VIOLATION

from eneo.authentication.browser_session_service import SessionWatch
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.logging import get_logger
from eneo.server.dependencies.container import get_user_from_websocket
from eneo.server.websockets.websocket_manager import websocket_manager
from eneo.server.websockets.websocket_models import (
    ENEO_SUBPROTOCOL,
    ParsedMessage,
)
from eneo.users.user import UserInDB

logger = get_logger(__name__)

# How often an open socket asks whether its session still admits it. Between
# the session's database checks (RECHECK_SECONDS) the answer is the clock.
_WATCH_SECONDS = 1.0

router = APIRouter()


@router.websocket("/ws")
@endpoint_access(
    authentication=Authentication.WEBSOCKET,
    authorization=Authorization.AUTHENTICATED,
    reason="WebSocketManager binds subscriptions to the authenticated user ID.",
)
async def connect(
    websocket: WebSocket,
    user: Annotated[UserInDB, Depends(get_user_from_websocket)],
):
    await websocket.accept(subprotocol=ENEO_SUBPROTOCOL)
    logger.debug(f"User {user.email} connected to websocket.")

    try:
        if user.browser_session is None:
            await _receive(websocket, user)
        else:
            # The socket keeps its user while it is open, so it serves a
            # browser session only while that session would admit a new
            # request (sign-out, a password change, a restricted account and
            # the token's expiry end it).
            await _receive_while_admitted(
                websocket, user, SessionWatch(user.browser_session, websocket)
            )
    finally:
        websocket_manager.unsubscribe_from_all_channels(websocket)

    logger.debug(f"WebSocket connection with user {user.email} has been closed.")


async def _receive(websocket: WebSocket, user: UserInDB) -> None:
    while True:
        try:
            raw_message = await websocket.receive_json()
            websocket_message = ParsedMessage(**raw_message)
            await websocket_manager.handle_message(
                websocket_message, websocket=websocket, user=user
            )
        except WebSocketDisconnect:
            logger.debug(f"User {user.email} disconnected from websocket.")
            return
        except Exception:
            # If anything happens while handling message, ignore it and keep the
            # connection going

            logger.exception("Exception happened while handling websocket message:")


async def _receive_while_admitted(
    websocket: WebSocket, user: UserInDB, admitted: SessionWatch
) -> None:
    async def watch() -> None:
        while await admitted():
            await asyncio.sleep(_WATCH_SECONDS)

    receiving = asyncio.create_task(_receive(websocket, user))
    watching = asyncio.create_task(watch())
    try:
        done, _ = await asyncio.wait(
            {receiving, watching}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        receiving.cancel()
        watching.cancel()
    if receiving not in done:
        # 1008: the client must not reconnect with the same token.
        await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="Session ended")
