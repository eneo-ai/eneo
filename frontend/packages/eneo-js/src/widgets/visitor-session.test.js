import { EneoError } from "../client/client.js";
import assert from "node:assert/strict";
import { describe, it, mock } from "node:test";
import { VisitorSession, storageKey } from "./visitor-session.js";
class MemoryStorage {
  store = new Map();
  getItem(key) {
    return this.store.get(key) ?? null;
  }
  setItem(key, value) {
    this.store.set(key, value);
  }
  removeItem(key) {
    this.store.delete(key);
  }
}
function rejected(status) {
  return new EneoError("nope", "SERVER", status, 0);
}
function setup(options = {}) {
  let now = 1_000_000;

  const createVisitorSession = mock.fn(async ({ previousToken, visitorId, altcha }) => ({
    token: `tok-${createVisitorSession.mock.callCount() + 1}${previousToken ? "-rot" : ""}${altcha ? "-pow" : ""}`,
    expires_in: 900,
    visitor_id: visitorId ?? "visitor-1",
    visitor_key: "key-1"
  }));
  const client = { createVisitorSession };
  const solve = mock.fn(async () => "payload");
  const storage = options.storage ?? new MemoryStorage();
  const session = new VisitorSession({
    client,
    config: {
      public_id: "wgt_x",
      bot_protection: options.botProtection ?? "altcha",
      token_generation: 0
    },
    solve,
    storage,
    now: () => now
  });
  return { session, createVisitorSession, solve, storage, advance: (ms) => (now += ms) };
}
describe("VisitorSession", () => {
  it("has no identity and stores nothing until a token is needed", () => {
    const { session, storage } = setup();
    assert.deepStrictEqual(session.hasIdentity, false);
    assert.strictEqual(session.token, null);
    assert.deepStrictEqual(storage.store.size, 0);
  });
  it("solves the challenge for a new visitor and persists the result", async () => {
    const { session, createVisitorSession, solve, storage } = setup();
    const token = await session.ensureToken();
    assert.deepStrictEqual(token, "tok-1-pow");
    assert.equal(solve.mock.callCount(), 1);
    assert.deepStrictEqual(createVisitorSession.mock.calls.at(-1).arguments, [
      { altcha: "payload" }
    ]);
    assert.partialDeepStrictEqual(JSON.parse(storage.getItem(storageKey("wgt_x"))), {
      visitor_id: "visitor-1",
      visitor_key: "key-1",
      token: "tok-1-pow"
    });
    assert.deepStrictEqual(session.hasIdentity, true);
  });
  it("reuses a valid token and shares one mint between concurrent callers", async () => {
    const { session, createVisitorSession } = setup();
    const [a, b] = await Promise.all([session.ensureToken(), session.ensureToken()]);
    assert.deepStrictEqual(a, b);
    assert.equal(createVisitorSession.mock.callCount(), 1);
    assert.deepStrictEqual(await session.ensureToken(), a);
    assert.equal(createVisitorSession.mock.callCount(), 1);
  });
  it("rotates silently with the previous token when it is near or past expiry", async () => {
    const { session, createVisitorSession, solve, advance } = setup();
    await session.ensureToken();
    advance(900 * 1000 - 5_000); // inside the 30 s margin
    const rotated = await session.ensureToken();
    assert.deepStrictEqual(rotated, "tok-2-rot");
    assert.deepStrictEqual(createVisitorSession.mock.calls.at(-1).arguments, [
      { previousToken: "tok-1-pow" }
    ]);
    assert.equal(solve.mock.callCount(), 1);
  });
  it("falls back to a new proof of work when rotation is rejected as stale", async () => {
    const { session, createVisitorSession, solve, advance } = setup();
    await session.ensureToken();
    advance(20 * 60 * 1000);
    createVisitorSession.mock.mockImplementationOnce(async () => {
      throw rejected(401);
    });
    const token = await session.ensureToken();
    assert.deepStrictEqual(token, "tok-3-pow");
    assert.equal(solve.mock.callCount(), 2);
    // The visitor id is carried over so continuity survives the re-challenge.
    assert.deepStrictEqual(createVisitorSession.mock.calls.at(-1).arguments, [
      {
        altcha: "payload",
        visitorId: "visitor-1",
        visitorKey: "key-1"
      }
    ]);
  });
  it("does not rotate a token that is past the grace window", async () => {
    const { session, createVisitorSession, solve, advance } = setup();
    await session.ensureToken();
    advance(3 * 60 * 60 * 1000);
    assert.deepStrictEqual(session.hasIdentity, false);
    await session.ensureToken();
    assert.deepStrictEqual(createVisitorSession.mock.calls.at(-1).arguments, [
      {
        altcha: "payload",
        visitorId: "visitor-1",
        visitorKey: "key-1"
      }
    ]);
    assert.equal(solve.mock.callCount(), 2);
  });
  it("skips the challenge when the widget has bot protection off", async () => {
    const { session, createVisitorSession, solve } = setup({ botProtection: "none" });
    await session.ensureToken();
    assert.equal(solve.mock.callCount(), 0);
    assert.deepStrictEqual(createVisitorSession.mock.calls.at(-1).arguments, [{}]);
  });
  it("solves a newly required challenge without reloading an open widget", async () => {
    const { session, createVisitorSession, solve } = setup({ botProtection: "none" });
    createVisitorSession.mock.mockImplementationOnce(async () => {
      throw new EneoError("required", "RESPONSE", 400, 0, {
        detail: { code: "challenge_required" }
      });
    });
    await session.ensureToken();
    assert.deepStrictEqual(createVisitorSession.mock.calls[0].arguments, [{}]);
    assert.deepStrictEqual(createVisitorSession.mock.calls[1].arguments, [{ altcha: "payload" }]);
    assert.equal(solve.mock.callCount(), 1);
  });
  it("restores a remembered session from storage and can be invalidated", async () => {
    const storage = new MemoryStorage();
    const first = setup({ storage });
    await first.session.ensureToken();
    first.session.rememberSession("sess-1");
    const second = setup({ storage });
    assert.deepStrictEqual(second.session.sessionId, "sess-1");
    assert.deepStrictEqual(second.session.visitorId, "visitor-1");
    assert.deepStrictEqual(second.session.hasIdentity, true);
    second.session.invalidate();
    assert.deepStrictEqual(second.session.token, "");
    assert.deepStrictEqual(second.session.hasIdentity, false);
    assert.deepStrictEqual(second.session.sessionId, "sess-1");
    await second.session.ensureToken();
    assert.deepEqual(second.createVisitorSession.mock.calls.at(-1).arguments, [
      {
        altcha: "payload",
        visitorId: "visitor-1",
        visitorKey: "key-1"
      }
    ]);
    second.session.clear();
    assert.deepStrictEqual(storage.store.size, 0);
  });
  it("survives corrupt storage", () => {
    const storage = new MemoryStorage();
    storage.setItem(storageKey("wgt_x"), "{not json");
    const { session } = setup({ storage });
    assert.strictEqual(session.token, null);
  });
  it("keeps the chat usable and clears its identity when storage access is revoked", async () => {
    const storage = new MemoryStorage();
    const { session } = setup({ storage });
    await session.ensureToken();
    storage.setItem = () => {
      throw new Error("Storage blocked");
    };
    storage.removeItem = () => {
      throw new Error("Storage blocked");
    };
    assert.doesNotThrow(() => session.rememberSession("s1"));
    assert.equal(session.sessionId, "s1");
    assert.doesNotThrow(() => session.clear());
    assert.equal(session.token, null);
    assert.equal(session.hasIdentity, false);
    assert.equal(session.sessionId, null);
  });
  it("uses a preview token as is and never stores or rotates it", async () => {
    const storage = new MemoryStorage();
    const createVisitorSession = mock.fn();
    const session = new VisitorSession({
      client: { createVisitorSession },
      config: { public_id: "wgt_x", bot_protection: "altcha", token_generation: 0 },
      solve: mock.fn(),
      storage,
      fixedToken: "preview-token"
    });
    assert.deepStrictEqual(session.isPreview, true);
    assert.deepStrictEqual(session.token, "preview-token");
    assert.deepStrictEqual(await session.ensureToken(), "preview-token");
    assert.deepStrictEqual(session.hasIdentity, false);
    session.rememberSession("s1");
    assert.equal(createVisitorSession.mock.callCount(), 0);
    assert.deepStrictEqual(storage.store.size, 0);
  });
});
