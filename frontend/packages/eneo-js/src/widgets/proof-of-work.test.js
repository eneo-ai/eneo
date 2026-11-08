import { createWidgetClient } from "../widget.js";
import { EneoError } from "../client/client.js";
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { AltchaSolveError, solveWithAltcha, VERIFICATION_TIMEOUT_MS } from "./proof-of-work.js";

const challenge = {
  parameters: { algorithm: "SHA-256", nonce: "abcd", salt: "00", cost: 1000, keyPrefix: "0" },
  signature: "signed"
};
const client = () => createWidgetClient({ baseUrl: "https://eneo.test", publicId: "wgt_test" });
const solution = { counter: 1, derivedKey: "00", time: 1 };
const workers = [];
let mode = "answer";
const originalWorker = globalThis.Worker;

class TestWorker extends EventTarget {
  terminated = false;
  constructor(url) {
    super();
    this.url = url;
    workers.push(this);
  }
  postMessage(message) {
    if (message.type !== "work") return;
    this.work = message;
    if (mode === "answer")
      queueMicrotask(() =>
        this.dispatchEvent(Object.assign(new Event("message"), { data: solution }))
      );
    if (mode === "error") queueMicrotask(() => this.dispatchEvent(new Event("error")));
  }
  terminate() {
    this.terminated = true;
  }
}

beforeEach(() => {
  workers.length = 0;
  mode = "answer";
  globalThis.Worker = TestWorker;
});
afterEach(() => {
  if (originalWorker === undefined) delete globalThis.Worker;
  else globalThis.Worker = originalWorker;
});

function fetchChallenge(t, value = challenge) {
  return t.mock.method(globalThis, "fetch", async () => Response.json(value));
}

test("fetches without cookies, uses one vendor worker and returns the signed ALTCHA payload", async (t) => {
  const fetch = fetchChallenge(t);
  const payload = await solveWithAltcha(client());
  assert.deepEqual(JSON.parse(atob(payload)), { challenge, solution });
  assert.equal(fetch.mock.calls[0].arguments[1].credentials, "omit");
  assert.equal(workers.length, 1);
  assert.equal(workers[0].work.counterStep, 1);
  assert.ok(workers.every((worker) => worker.terminated));
});

test("an HTTP failure cannot produce a payload or start hashing", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json(
      { detail: { code: "rate_limited_challenge", message: "Wait" } },
      { status: 429, headers: { "Retry-After": "30" } }
    )
  );
  await assert.rejects(
    solveWithAltcha(client()),
    (error) =>
      error instanceof EneoError &&
      error.status === 429 &&
      error.headers.get("Retry-After") === "30"
  );
  assert.equal(workers.length, 0);
});

test("a stalled worker reaches a deadline, terminates and allows a fresh attempt", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  fetchChallenge(t);
  mode = "hang";
  const verification = solveWithAltcha(client());
  const rejected = assert.rejects(verification, AltchaSolveError);
  // Yield to the response body and the library before advancing the deadline.
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(workers.length, 1);
  t.mock.timers.tick(VERIFICATION_TIMEOUT_MS);
  await rejected;
  assert.ok(workers[0].terminated);
  mode = "answer";
  await solveWithAltcha(client());
  assert.equal(workers.length, 2);
  assert.ok(workers.every((worker) => worker.terminated));
});

test("a stalled challenge fetch reaches the same deadline and is aborted", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const fetch = t.mock.method(globalThis, "fetch", () => new Promise(() => {}));
  const rejected = assert.rejects(solveWithAltcha(client()), AltchaSolveError);
  t.mock.timers.tick(VERIFICATION_TIMEOUT_MS);
  await rejected;
  assert.equal(fetch.mock.calls[0].arguments[1].signal.aborted, true);
  assert.equal(workers.length, 0);
});

test("leaving the chat cancels a stalled challenge fetch", async (t) => {
  const controller = new AbortController();
  const fetch = t.mock.method(globalThis, "fetch", () => new Promise(() => {}));
  const rejected = assert.rejects(
    solveWithAltcha(client(), { signal: controller.signal }),
    AltchaSolveError
  );
  controller.abort();
  await rejected;
  assert.equal(fetch.mock.calls[0].arguments[1].signal.aborted, true);
  assert.equal(workers.length, 0);
});

test("leaving the chat terminates a stalled worker", async (t) => {
  fetchChallenge(t);
  mode = "hang";
  const controller = new AbortController();
  const rejected = assert.rejects(
    solveWithAltcha(client(), { signal: controller.signal }),
    AltchaSolveError
  );
  await new Promise((resolve) => setImmediate(resolve));
  controller.abort();
  await rejected;
  assert.ok(workers[0].terminated);
});

test("worker startup errors and unsupported algorithms fail closed", async (t) => {
  const fetch = fetchChallenge(t);
  mode = "error";
  await assert.rejects(solveWithAltcha(client()), AltchaSolveError);
  assert.ok(workers[0].terminated);
  fetch.mock.mockImplementation(async () =>
    Response.json({ ...challenge, parameters: { ...challenge.parameters, algorithm: "unknown" } })
  );
  await assert.rejects(solveWithAltcha(client()), AltchaSolveError);
  assert.equal(workers.length, 1);
});
