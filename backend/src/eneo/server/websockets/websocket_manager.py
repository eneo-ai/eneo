import asyncio
import traceback
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import WebSocket

from eneo.main.logging import get_logger
from eneo.main.models import Channel, ChannelType, RedisMessage
from eneo.server.websockets.websocket_models import (
    IncomingMessageType,
    OutGoingMessageType,
    ParsedMessage,
    Space,
    WsAppRunUpdate,
    WsOutgoingWebSocketMessage,
    WsSubscribeMessage,
    WsUnSubscribeMessage,
)
from eneo.users.user import UserInDB
from eneo.worker.redis import r


@dataclass
class SubscribedChannels:
    websockets: set[WebSocket]
    redis_task: asyncio.Task[Any]


logger = get_logger(__name__)


class WebSocketManager:
    def __init__(
        self,
        redis: aioredis.Redis,
        channels: dict[str, SubscribedChannels] | None = None,
    ):
        super().__init__()
        self.redis = redis
        self.channels = channels or {}
        self.task_monitoring = None

    @property
    def tasks(self) -> list[asyncio.Task[Any]]:
        return [self.channels[channel].redis_task for channel in self.channels]

    def _check_exceptions(self, task: asyncio.Task[Any]) -> None:
        try:
            _ = task.result()
        except asyncio.exceptions.CancelledError:
            logger.debug(f"Task {task.get_name()} was cancelled")
        except Exception:
            logger.exception(traceback.format_exc())

    def _remove_websocket_if_exists(self, websocket: WebSocket, channel: str) -> None:
        try:
            self.channels[channel].websockets.remove(websocket)
        except KeyError:
            logger.debug(f"WebSocket not found in channel {channel}")

    async def _listen_to_redis(self, channel: str) -> None:
        redis_client = cast(Any, self.redis)
        pubsub = redis_client.pubsub()
        async with pubsub:
            await pubsub.subscribe(channel)
            logger.debug("Subscribed to Redis channel: %s", channel)

            while True:
                raw_message = cast(
                    dict[str, Any] | None,
                    await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=None
                    ),
                )
                if raw_message is not None:
                    await self._process_redis_message(channel, raw_message)

    @staticmethod
    def _parse_uuid(value: Any) -> UUID | None:
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _build_space(additional_data: dict[str, Any] | None) -> Space | None:
        if additional_data is None:
            return None
        space_data_raw = additional_data.get("space")
        if not isinstance(space_data_raw, dict):
            return None
        space_data = cast(dict[str, Any], space_data_raw)
        space_id = WebSocketManager._parse_uuid(space_data.get("id"))
        personal = space_data.get("personal")
        if space_id is None or not isinstance(personal, bool):
            return None
        return Space(id=space_id, personal=personal)

    async def _process_redis_message(
        self, channel: str, raw_message: dict[str, Any]
    ) -> None:
        raw_data = raw_message.get("data")
        if isinstance(raw_data, bytes):
            payload = raw_data.decode()
        elif isinstance(raw_data, str):
            payload = raw_data
        else:
            return

        message = RedisMessage.model_validate_json(payload)
        message_data = message.model_dump()
        additional_data = cast(
            dict[str, Any] | None, message_data.get("additional_data")
        )
        await self.publish(
            channel,
            message=WsOutgoingWebSocketMessage(
                type=OutGoingMessageType.APP_RUN_UPDATES,
                data=WsAppRunUpdate(
                    id=message.id,
                    status=message.status,
                    app_id=self._parse_uuid(additional_data.get("app_id"))
                    if additional_data is not None
                    else None,
                    space=self._build_space(additional_data),
                ),
            ),
        )

    async def _send_message(
        self, websocket: WebSocket, message: WsOutgoingWebSocketMessage
    ) -> None:
        await websocket.send_text(
            message.model_dump_json(serialize_as_any=True, exclude_none=True)
        )

    async def pong(self, websocket: WebSocket) -> None:
        message = WsOutgoingWebSocketMessage(type=OutGoingMessageType.PONG)
        await self._send_message(websocket, message)

    async def handle_message(
        self, websocket_message: ParsedMessage, websocket: WebSocket, user: UserInDB
    ) -> None:
        match websocket_message.type:
            case IncomingMessageType.PING:
                await self.pong(websocket)
            case IncomingMessageType.SUBSCRIBE:
                assert websocket_message.data is not None
                subscribe_message = cast(WsSubscribeMessage, websocket_message.data)
                self.subscribe(
                    websocket,
                    channel_type=subscribe_message.channel,
                    user_id=user.id,
                )
            case IncomingMessageType.UNSUBSCRIBE:
                assert websocket_message.data is not None
                unsubscribe_message = cast(WsUnSubscribeMessage, websocket_message.data)
                self.unsubscribe(
                    websocket,
                    channel_type=unsubscribe_message.channel,
                    user_id=user.id,
                )
            case _:
                raise ValueError(f"Unexpected message type: {websocket_message.type}")

    def subscribe(
        self, websocket: WebSocket, channel_type: ChannelType, user_id: UUID
    ) -> None:
        channel = Channel(type=channel_type, user_id=user_id).channel_string

        if channel not in self.channels:
            redis_task = asyncio.create_task(self._listen_to_redis(channel))
            redis_task.add_done_callback(self._check_exceptions)
            self.channels[channel] = SubscribedChannels(
                websockets=set(), redis_task=redis_task
            )

        self.channels[channel].websockets.add(websocket)

    def unsubscribe(
        self, websocket: WebSocket, channel_type: ChannelType, user_id: UUID
    ) -> None:
        channel = Channel(type=channel_type, user_id=user_id).channel_string

        if channel in self.channels:
            self._remove_websocket_if_exists(websocket, channel)

            if not self.channels[channel].websockets:
                # No one is listening, cancel the task
                self.channels[channel].redis_task.cancel()
                del self.channels[channel]

    def unsubscribe_from_all_channels(self, websocket: WebSocket) -> None:
        channels_to_delete: list[str] = []
        for channel in self.channels:
            self._remove_websocket_if_exists(websocket, channel)

            if not self.channels[channel].websockets:
                channels_to_delete.append(channel)

        for channel in channels_to_delete:
            self.channels[channel].redis_task.cancel()
            del self.channels[channel]

    async def publish(self, channel: str, message: WsOutgoingWebSocketMessage) -> None:
        subscribed_channels = self.channels.get(channel, None)

        if subscribed_channels is not None:
            for ws in subscribed_channels.websockets:
                await self._send_message(ws, message)

    async def shutdown(self) -> None:
        for task in self.tasks:
            task.cancel()

        await asyncio.gather(*self.tasks)


websocket_manager = WebSocketManager(redis=r)
