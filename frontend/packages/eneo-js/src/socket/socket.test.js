import assert from "node:assert/strict";
import test, { mock } from "node:test";
import { createEneoSocket } from "./socket.js";

const PING_INTERVAL = 30 * 1000;
const PONG_TIMEOUT = 20 * 1000;

/** Records every socket the client opens and every message it sends. */
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  /** @type {FakeWebSocket[]} */
  static opened = [];

  constructor() {
    this.readyState = FakeWebSocket.CONNECTING;
    /** @type {unknown[]} */
    this.sent = [];
    FakeWebSocket.opened.push(this);
  }

  /** @param {string} message */
  send(message) {
    this.sent.push(JSON.parse(message));
  }

  addEventListener() {}

  close() {}

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** @param {number} code */
  closedByServer(code) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

/** @param {import("node:test").TestContext} t */
function connected(t) {
  FakeWebSocket.opened = [];
  const original = globalThis.WebSocket;
  // @ts-expect-error the fake has what the client uses
  globalThis.WebSocket = FakeWebSocket;
  mock.timers.enable({ apis: ["setInterval", "setTimeout"] });
  t.after(() => {
    mock.timers.reset();
    globalThis.WebSocket = original;
  });
  createEneoSocket({ baseUrl: "https://eneo.example", token: "token" }).connect();
  const [socket] = FakeWebSocket.opened;
  socket.open();
  return socket;
}

test("a socket the server closes with 1008 stays closed", (t) => {
  const socket = connected(t);

  // A ping is out, waiting for its pong, when the session ends.
  mock.timers.tick(PING_INTERVAL);
  assert.deepEqual(socket.sent, [{ type: "ping" }]);
  socket.closedByServer(1008);
  for (let cycle = 0; cycle < 10; cycle++) {
    mock.timers.tick(PING_INTERVAL);
    mock.timers.tick(PONG_TIMEOUT);
  }

  // The same token cannot open another: no reconnect, no further pings.
  assert.equal(FakeWebSocket.opened.length, 1);
  assert.deepEqual(socket.sent, [{ type: "ping" }]);
});

test("a lost pong still reconnects", (t) => {
  connected(t);

  mock.timers.tick(PING_INTERVAL);
  mock.timers.tick(PONG_TIMEOUT);

  assert.equal(FakeWebSocket.opened.length, 2);
});
