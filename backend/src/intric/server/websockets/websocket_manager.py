import asyncio
import traceback
from dataclasses import dataclass
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import WebSocket

from intric.main.logging import get_logger
from intric.main.models import Channel, ChannelType, RedisMessage
from intric.server.websockets.websocket_models import (
    IncomingMessageType,
    OutGoingMessageType,
    ParsedMessage,
    Space,
    WsAppRunUpdate,
    WsOutgoingWebSocketMessage,
)
from intric.users.user import UserInDB
from intric.worker.redis import r


@dataclass
class SubscribedChannels:
    websockets: set[WebSocket]
    redis_task: asyncio.Task


logger = get_logger(__name__)


class WebSocketManager:
    def __init__(
        self,
        redis: aioredis.Redis,
        channels: dict[str, SubscribedChannels] = None,
    ):
        self.redis = redis
        self.channels = channels or {}
        self.task_monitoring = None

    @property
    def tasks(self):
        return [self.channels[channel].redis_task for channel in self.channels]

    def _check_exceptions(self, task: asyncio.Task):
        try:
            _ = task.result()
        except asyncio.exceptions.CancelledError:
            logger.debug(f"Task {task.get_name()} was cancelled")
        except Exception:
            logger.exception(traceback.format_exc())

    def _remove_websocket_if_exists(self, websocket, channel):
        try:
            self.channels[channel].websockets.remove(websocket)
        except KeyError:
            logger.debug(f"WebSocket not found in channel {channel}")

    async def _listen_to_redis(self, channel: str):
        async with self.redis.pubsub() as pubsub:
            await pubsub.subscribe(channel)
            logger.debug("Subscribed to Redis channel: %s", channel)

            while True:
                raw_message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=None
                )
                if raw_message is not None:
                    await self._process_redis_message(channel, raw_message)

    async def _process_redis_message(self, channel: str, raw_message: dict):
        message = RedisMessage.model_validate_json(raw_message["data"].decode())
        additional_data = message.additional_data
        additional_data_present = bool(additional_data)
        await self.publish(
            channel,
            message=WsOutgoingWebSocketMessage(
                type=OutGoingMessageType.APP_RUN_UPDATES,
                data=WsAppRunUpdate(
                    id=message.id,
                    status=message.status,
                    app_id=(
                        additional_data["app_id"]
                        if additional_data_present and additional_data is not None
                        else None
                    ),
                    space=(
                        Space(
                            id=additional_data["space"]["id"],
                            personal=additional_data["space"]["personal"],
                        )
                        if additional_data_present and additional_data is not None
                        else None
                    ),
                ),
            ),
        )

    async def _send_message(
        self, websocket: WebSocket, message: WsOutgoingWebSocketMessage
    ):
        await websocket.send_text(
            message.model_dump_json(serialize_as_any=True, exclude_none=True)
        )

    async def pong(self, websocket: WebSocket):
        message = WsOutgoingWebSocketMessage(type=OutGoingMessageType.PONG)
        await self._send_message(websocket, message)

    async def handle_message(
        self, websocket_message: ParsedMessage, websocket: WebSocket, user: UserInDB
    ):
        match websocket_message.type:
            case IncomingMessageType.PING:
                await self.pong(websocket)
            case IncomingMessageType.SUBSCRIBE:
                assert websocket_message.data is not None
                self.subscribe(
                    websocket,
                    channel_type=websocket_message.data.channel,  # type: ignore[attr-defined]
                    user_id=user.id,
                )
            case IncomingMessageType.UNSUBSCRIBE:
                assert websocket_message.data is not None
                self.unsubscribe(
                    websocket,
                    channel_type=websocket_message.data.channel,  # type: ignore[attr-defined]
                    user_id=user.id,
                )
            case _:
                raise ValueError(f"Unexpected message type: {websocket_message.type}")

    def subscribe(self, websocket: WebSocket, channel_type: ChannelType, user_id: UUID):
        channel = Channel(type=channel_type, user_id=user_id).channel_string

        if channel not in self.channels:
            redis_task = asyncio.create_task(self._listen_to_redis(channel))
            redis_task.add_done_callback(self._check_exceptions)
            self.channels[channel] = SubscribedChannels(
                websockets=set(), redis_task=redis_task
            )

        self.channels[channel].websockets.add(websocket)

    def unsubscribe(self, websocket: WebSocket, channel_type: Channel, user_id: UUID):
        channel = Channel(type=channel_type, user_id=user_id).channel_string

        if channel in self.channels:
            self._remove_websocket_if_exists(websocket, channel)

            if not self.channels[channel].websockets:
                # No one is listening, cancel the task
                self.channels[channel].redis_task.cancel()
                del self.channels[channel]

    def unsubscribe_from_all_channels(self, websocket: WebSocket):
        channels_to_delete = []
        for channel in self.channels:
            self._remove_websocket_if_exists(websocket, channel)

            if not self.channels[channel].websockets:
                channels_to_delete.append(channel)

        for channel in channels_to_delete:
            self.channels[channel].redis_task.cancel()
            del self.channels[channel]

    async def publish(self, channel: str, message: WsOutgoingWebSocketMessage):
        subscribed_channels = self.channels.get(channel, None)

        if subscribed_channels is not None:
            for ws in subscribed_channels.websockets:
                await self._send_message(ws, message)

    async def shutdown(self):
        for task in self.tasks:
            task.cancel()

        await asyncio.gather(*self.tasks)


websocket_manager = WebSocketManager(redis=r)
