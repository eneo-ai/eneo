const HEARTBEAT = {
  /** How often to send the ping/pong message in ms */
  INTERVAL: 30 * 1000,
  /** How long to wait for a response before reconnecting */
  TIMEOUT: 20 * 1000
};

/** The server closes an open socket with this code when its session ended. */
const SESSION_ENDED = 1008;

/**
 * Waits before opening a socket again after one closed: doubling from the first
 * to the last, back to the first once a socket opens. A refused handshake looks
 * like a dropped network (1006), so the client never gives up; it only asks
 * less often.
 */
const RETRY = {
  FIRST: 2 * 1000,
  LAST: 5 * 60 * 1000
};

/** @typedef {import("./types").ServerMessages} ServerMessages*/
/** @typedef {import("./types").ClientSubscribableMessageType} ClientSubscribableMessageType*/

/**
 * Create an Eneo.js object to interact with the eneo backend.
 * Requires either an api key or a user token to authenticate requests.
 * @param {Object} args
 * @param {string} args.baseUrl Backend base url
 * @param {string} args.token Eneo auth token obtained through logging in
 * @param {Object} [options]
 * @param {Array<ClientSubscribableMessageType>} [options.defaultSubscriptions]
 * */
export function createEneoSocket(args, options) {
  const { baseUrl, token } = args;
  /**
   * The main socket connection
   * @type {WebSocket | null} */
  let socket = null;
  /**
   * A map of handler functions to run when a specific message is received
   * @type {import("./types").MessageHandlers} */
  const handlers = new Map();
  /**
   * A reference counter of subscriptions, so we only unsub if there are no subscribers left
   * @type {Map<ClientSubscribableMessageType, number>} */
  const currentSubscriptions = new Map();

  function connect() {
    const url = new URL(baseUrl);
    // In local dev we do not always have SSL
    url.protocol = url.protocol === "http:" ? "ws:" : "wss:";
    url.pathname = "api/v1/ws";
    // Each attempt starts from nothing: no heartbeat or retry of an earlier one.
    stopTimers();
    socket = new WebSocket(url.toString(), ["eneo", `auth_${token}`]);
    socket.onmessage = dispatchToHandlers;
    socket.onclose = (event) => {
      stopTimers();
      socket = null;
      // A session that ended (signed out, expired) is final: the same token
      // cannot open another socket.
      if (event.code === SESSION_ENDED) return;
      retryTimeout = setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, RETRY.LAST);
    };
    socket.onopen = () => {
      retryDelay = RETRY.FIRST;
      startHeartbeat();
      initSubscriptions();
    };

    return disconnect;
  }

  function safelyCloseSocket() {
    if (socket) {
      // 1. Remove the automatic reconnect handler to prevent the socket from reconnecting
      socket.onclose = () => {};
      // 2. Now we can close the socket without it starting up again
      socket.close();
      // 3. Potential memory leak: If the socket was still running here it would not be garbage collected
      // We prevent that leak by removing the auto reconnect in `onclose`
      socket = null;
    }
  }

  function disconnect() {
    // Only an existing socket can be told; the local state goes either way,
    // also after a 1008 left none, so a later connect starts clean.
    if (socket) {
      currentSubscriptions.forEach((count, type) => {
        sendMessage({ type: "unsubscribe", data: { channel: type } });
      });
    }
    currentSubscriptions.clear();
    handlers.clear();
    stopTimers();
    retryDelay = RETRY.FIRST;
    safelyCloseSocket();
  }

  /** @param {MessageEvent} event */
  function dispatchToHandlers(event) {
    try {
      /** @type {import("./types").WebsocketMessage} */
      const { type, data } = JSON.parse(event.data);
      if (type === "pong") {
        clearTimeout(heartbeatReconnectTimeout);
        return;
      }
      handlers.get(type)?.forEach((handler) => handler(data));
    } catch (error) {
      console.error("Failed to parse message: ", error);
    }
  }

  /**
   * Register a handler function for a specifc message type.
   *
   * __IMPORTANT__: Only use this function if you want to register a handler for a message type that is not subscribable,
   * otherwise use the `subscribe` function instead, which will make sure that you are actually subscribed to that message type
   * @type {<T extends keyof ServerMessages>(type: T, callback: (data: ServerMessages[T]) => void) => (() => void)}
   */
  function registerHandler(type, callback) {
    handlers.set(type, (handlers.get(type) ?? new Set()).add(callback));
    return () => handlers.get(type)?.delete(callback);
  }

  /**
   * Subscribe to a specific message type, optionally supply a handler for this message type.
   * Using this function will make sure you're properly subscribed if you want to handle a subscribable message type
   * @param type The message type to subscribe to
   * @param handler An optional handler function to handle that message type
   * @type {<T extends ClientSubscribableMessageType>
   * (type: T, handler?: (data: ServerMessages[T]) => void) => (() => void)}
   * @returns {() => void} A corresponding unsubscriber, which will also remove the handler if it was set
   * */
  function subscribe(type, handler) {
    const removeHandler = handler ? registerHandler(type, handler) : null;
    // We always subscribe, no harm in that
    sendMessage({ type: "subscribe", data: { channel: type } });
    currentSubscriptions.set(type, (currentSubscriptions.get(type) ?? 0) + 1);
    return () => {
      removeHandler?.();
      const remainingSubscribers = currentSubscriptions.get(type);
      if (remainingSubscribers && remainingSubscribers > 1) {
        currentSubscriptions.set(type, remainingSubscribers - 1);
      } else {
        currentSubscriptions.delete(type);
        sendMessage({ type: "unsubscribe", data: { channel: type } });
      }
    };
  }

  /**
   * Simple typed wrapper around `socket.send`, will wait to send if socket is connecting
   * @param {import("./types").WebsocketRequest} message
   * @throws {Error} Throws an error if the socket is closed or does not exist
   */
  async function sendMessage(message) {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    } else if (socket?.readyState === WebSocket.CONNECTING) {
      socket.addEventListener("open", () => socket?.send(JSON.stringify(message)), { once: true });
    } else {
      throw new Error(`WebSocket is closed or closing\n${JSON.stringify(message)}`);
    }
  }

  /** @type { ReturnType<typeof setTimeout> | undefined } Hartbeat reconnect timeout */
  let heartbeatReconnectTimeout = undefined;
  /** @type { ReturnType<typeof setInterval> | undefined } Heartbeat ping interval  */
  let heartbeatInterval = undefined;
  /** @type { ReturnType<typeof setTimeout> | undefined } The next attempt after a close */
  let retryTimeout = undefined;
  let retryDelay = RETRY.FIRST;

  function stopTimers() {
    clearTimeout(retryTimeout);
    clearTimeout(heartbeatReconnectTimeout);
    clearInterval(heartbeatInterval);
  }

  function startHeartbeat() {
    heartbeatInterval = setInterval(() => {
      sendMessage({ type: "ping" }).catch(() => {});
      clearTimeout(heartbeatReconnectTimeout);
      heartbeatReconnectTimeout = setTimeout(() => {
        // No pong: the connection is gone without a close. Open a new one now,
        // which also heals the subscriptions.
        safelyCloseSocket();
        connect();
      }, HEARTBEAT.TIMEOUT);
    }, HEARTBEAT.INTERVAL);
  }

  /**
   * Will init default subscriptions or try to heal lost subscriptions after a re-connect that was
   * caused by a lost connection (i.e. not user intent). But this is not thoroughly tested TBH
   */
  function initSubscriptions() {
    if (currentSubscriptions.size > 0) {
      currentSubscriptions.forEach((count, type) => {
        // We're not calling `subscribe` here as we want to retain the state we had before losing the connection
        sendMessage({ type: "subscribe", data: { channel: type } });
      });
    } else {
      // If there were not subscriptions found we're either running a first connect, or there are no default subscriptions
      options?.defaultSubscriptions?.forEach((type) => subscribe(type));
    }
  }

  return Object.freeze({
    /**
     * Initiate the websocket connection.
     * @returns Returns the disconnect function that can be used to close the socket.
     */
    connect,
    /**
     * Close the socket manually and do not try to reconnect. Will unregister all handlers and clear the subscriptions
     */
    disconnect,
    /**
     * Subscribe to a specific channel; will return the corresponding unsubrscriber.
     *
     * Optionally supply a handler for this message type.
     * Using this function will make sure you're properly subscribed if you want to handle a subscribable message type.
     *
     * __IMPORTANT__: Pay attention to always unsubscribe from channels that are no longer needed, as this is a risk for memory leaks.
     * If you subscribe to a topic in onMount() you can just return the unsubscriber which then will be run on unmount.
     * @return The unsubscribe function
     * */
    subscribe,
    /**
     * Register a callback for a specific message type; will return the the corresponding un-register function.
     *
     * __IMPORTANT__: Only use this function if you want to register a handler for a message type that is not subscribable,
     * otherwise use the `subscribe` function instead, which will make sure that you are actually subscribed to that message type
     * @returns A function to remove this handler from the socket
     */
    registerHandler
  });
}
