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
  const client = createEneoSocket({ baseUrl: "https://eneo.example", token: "token" });
  client.connect();
  const [socket] = FakeWebSocket.opened;
  socket.open();
  return { client, socket };
}

test("a socket the server closes with 1008 stays closed", (t) => {
  const { socket } = connected(t);

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

test("a socket the server closes with 1013 reconnects and subscribes again", async (t) => {
  /** @type {unknown[]} */
  const unhandled = [];
  const record = (/** @type {unknown} */ reason) => unhandled.push(reason);
  process.on("unhandledRejection", record);
  t.after(() => process.off("unhandledRejection", record));
  const { client, socket } = connected(t);
  client.subscribe("app_run_updates");
  socket.closedByServer(1013);

  mock.timers.tick(PING_INTERVAL);
  mock.timers.tick(PONG_TIMEOUT);
  const reopened = FakeWebSocket.opened[1];
  reopened.open();
  await new Promise((resolve) => setImmediate(resolve));

  // The session check got no answer: the client opens a new socket, which
  // authenticates again, and asks for the channels it had.
  assert.deepEqual(reopened.sent, [{ type: "subscribe", data: { channel: "app_run_updates" } }]);
  assert.deepEqual(unhandled, []);
});

test("a disconnect after a 1008 ends the subscriptions it held", (t) => {
  const { client, socket } = connected(t);
  /** @type {unknown[]} */
  const seen = [];
  client.subscribe("app_run_updates", (data) => seen.push(data));
  socket.closedByServer(1008);

  client.disconnect();
  client.connect();
  const reopened = FakeWebSocket.opened[1];
  reopened.open();
  reopened.onmessage?.({ data: JSON.stringify({ type: "app_run_updates", data: 1 }) });

  // The new connection starts clean: no old channel, no old handler.
  assert.deepEqual(reopened.sent, []);
  assert.deepEqual(seen, []);
});

const FIRST_RETRY = 2 * 1000;
const LAST_RETRY = 5 * 60 * 1000;

/** Ticks until the client opens its next socket; returns how long that took. */
function untilNextSocket() {
  const before = FakeWebSocket.opened.length;
  let waited = 0;
  while (FakeWebSocket.opened.length === before && waited <= LAST_RETRY) {
    mock.timers.tick(1000);
    waited += 1000;
  }
  return waited;
}

test("refused connections are retried later and later, up to a ceiling", (t) => {
  const { socket } = connected(t);
  socket.closedByServer(1006);

  /** @type {number[]} */
  const waits = [];
  for (let attempt = 0; attempt < 10; attempt++) {
    waits.push(untilNextSocket());
    // The handshake is refused, as for a session that ended before it.
    FakeWebSocket.opened.at(-1)?.closedByServer(1006);
  }

  assert.deepEqual(
    waits,
    [2, 4, 8, 16, 32, 64, 128, 256, 300, 300].map((s) => s * 1000)
  );
});

test("an opened socket starts the retries from the beginning again", (t) => {
  const { socket } = connected(t);
  socket.closedByServer(1006);
  for (let attempt = 0; attempt < 4; attempt++) {
    untilNextSocket();
    FakeWebSocket.opened.at(-1)?.closedByServer(1006);
  }

  untilNextSocket();
  const reopened = FakeWebSocket.opened.at(-1);
  reopened?.open();
  reopened?.closedByServer(1006);

  assert.equal(untilNextSocket(), FIRST_RETRY);
});

test("reconnecting keeps one heartbeat, and its pong is still heard", (t) => {
  const { socket } = connected(t);
  socket.closedByServer(1006);
  for (let attempt = 0; attempt < 5; attempt++) {
    untilNextSocket();
    const next = FakeWebSocket.opened.at(-1);
    next?.open();
    next?.closedByServer(1006);
  }
  untilNextSocket();
  const current = /** @type {FakeWebSocket} */ (FakeWebSocket.opened.at(-1));
  current.open();
  const opened = FakeWebSocket.opened.length;

  for (let cycle = 0; cycle < 3; cycle++) {
    mock.timers.tick(PING_INTERVAL);
    current.onmessage?.({ data: JSON.stringify({ type: "pong" }) });
  }
  mock.timers.tick(PONG_TIMEOUT);

  // One ping per interval from one heartbeat, and each pong keeps it open.
  assert.deepEqual(current.sent, [{ type: "ping" }, { type: "ping" }, { type: "ping" }]);
  assert.equal(FakeWebSocket.opened.length, opened);
});
