from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator

from intric.main.models import ChannelType, Status

INTRIC_SUBPROTOCOL = "intric"


class OutGoingMessageType(str, Enum):
    PONG = "pong"
    APP_RUN_UPDATES = "app_run_updates"


class IncomingMessageType(str, Enum):
    PING = "ping"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


class MessagePayload(BaseModel):
    pass


class WsPing(MessagePayload):
    pass


class WsSubscribeMessage(MessagePayload):
    channel: ChannelType = ChannelType.APP_RUN_UPDATES


class WsUnSubscribeMessage(WsSubscribeMessage):
    pass


class ParsedMessage(BaseModel):
    type: IncomingMessageType
    data: MessagePayload | None = None

    @model_validator(mode="before")
    def validate_data(cls, values: Any):
        message_type = values.get("type")

        if message_type is None:
            raise ValueError("Message type is invalid")

        match message_type:
            case IncomingMessageType.PING:
                values["data"] = WsPing()
            case IncomingMessageType.SUBSCRIBE:
                values["data"] = WsSubscribeMessage(**values["data"])
            case IncomingMessageType.UNSUBSCRIBE:
                values["data"] = WsUnSubscribeMessage(**values["data"])
            case _:
                raise ValueError(f"Unsupported message type: {message_type}")

        return values


# Outgoing messages #


class WsOutgoingWebSocketMessage(BaseModel):
    type: OutGoingMessageType
    data: MessagePayload | None = None


class WsPong(MessagePayload):
    pass


class Space(BaseModel):
    id: UUID
    personal: bool


class WsAppRunUpdate(MessagePayload):
    id: UUID
    status: Status
    app_id: UUID | None = None
    space: Space | None = None


# Add the websocket models here in order to include them in the openapi schema
WS_MODELS = [WsOutgoingWebSocketMessage, WsAppRunUpdate]
