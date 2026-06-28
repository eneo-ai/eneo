import { type components } from "../types/schema";

// CLIENT MESSAGE TYPES -----------------------------------------------------------------
type ClientActionMessageTypes = "ping" | "subscribe" | "unsubscribe";
export type ClientSubscribableMessageType = "app_run_updates";

/** Simple map of type string to data type */
type ClientMessages = {
  subscribe: {
    channel: SubscribableMessageTypes;
  };
  unsubscribe: {
    channel: SubscribableMessageTypes;
  };
  ping: never;
};

export type WebsocketRequest = {
  [K in keyof ClientMessages]: {
    type: K;
    data?: ClientMessages[K];
  };
}[keyof ClientMessages];

// SERVER MESSAGE TYPES -----------------------------------------------------------------
type ServerMessageTypes = components["schemas"]["WsOutgoingWebSocketMessage"]["type"];

/** Simple map of type string to data type */
type ServerMessages = {
  app_run_updates: Omit<components["schemas"]["WsAppRunUpdate"], "$defs">;
  pong: never;
};

export type WebsocketMessage = {
  [K in keyof ServerMessages]: {
    type: K;
    data: ServerMessages[K];
  };
}[keyof ServerMessages];

type MessageHandlers = Map<keyof ServerMessages, Set<(data: ServerMessages[K]) => void>>;
