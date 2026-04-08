from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from intric.main.logging import get_logger
from intric.server.dependencies.container import get_user_from_websocket
from intric.server.websockets.websocket_manager import websocket_manager
from intric.server.websockets.websocket_models import (
    INTRIC_SUBPROTOCOL,
    ParsedMessage,
)
from intric.users.user import UserInDB

logger = get_logger(__name__)


router = APIRouter()


@router.websocket("/ws")
async def connect(
    websocket: WebSocket,
    user: Annotated[UserInDB, Depends(get_user_from_websocket)],
):
    await websocket.accept(subprotocol=INTRIC_SUBPROTOCOL)
    logger.debug(f"User {user.email} connected to websocket.")

    while True:
        try:
            raw_message = await websocket.receive_json()
            websocket_message = ParsedMessage(**raw_message)
            await websocket_manager.handle_message(
                websocket_message, websocket=websocket, user=user
            )
        except WebSocketDisconnect:
            logger.debug(f"User {user.email} disconnected from websocket.")
            websocket_manager.unsubscribe_from_all_channels(websocket)
            break
        except Exception:
            # If anything happens while handling message, ignore it and keep the
            # connection going

            logger.exception("Exception happened while handling websocket message:")

    logger.debug(f"WebSocket connection with user {user.email} has been closed.")
