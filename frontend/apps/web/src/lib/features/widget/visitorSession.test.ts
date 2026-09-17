import { EneoError, type WidgetClient } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";
import { VisitorSession, storageKey } from "./visitorSession";

class MemoryStorage {
  store = new Map<string, string>();
  getItem(key: string) {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.store.set(key, value);
  }
  removeItem(key: string) {
    this.store.delete(key);
  }
}

function rejected(status: number) {
  return new EneoError("nope", "SERVER", status, 0);
}

function setup(options: { botProtection?: "altcha" | "none"; storage?: MemoryStorage } = {}) {
  let now = 1_000_000;
  const createVisitorSession = vi.fn(async ({ previousToken, visitorId, altcha }) => ({
    token: `tok-${createVisitorSession.mock.calls.length}${previousToken ? "-rot" : ""}${altcha ? "-pow" : ""}`,
    expires_in: 900,
    visitor_id: visitorId ?? "visitor-1"
  }));
  const client = { createVisitorSession } as unknown as WidgetClient;
  const solve = vi.fn(async () => "payload");
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
  return { session, createVisitorSession, solve, storage, advance: (ms: number) => (now += ms) };
}

describe("VisitorSession", () => {
  it("has no identity and stores nothing until a token is needed", () => {
    const { session, storage } = setup();
    expect(session.hasIdentity).toBe(false);
    expect(session.token).toBeNull();
    expect(storage.store.size).toBe(0);
  });

  it("solves the challenge for a new visitor and persists the result", async () => {
    const { session, createVisitorSession, solve, storage } = setup();
    const token = await session.ensureToken();
    expect(token).toBe("tok-1-pow");
    expect(solve).toHaveBeenCalledTimes(1);
    expect(createVisitorSession).toHaveBeenCalledWith({ altcha: "payload", visitorId: undefined });
    expect(JSON.parse(storage.getItem(storageKey("wgt_x"))!)).toMatchObject({
      visitor_id: "visitor-1",
      token: "tok-1-pow"
    });
    expect(session.hasIdentity).toBe(true);
  });

  it("reuses a valid token and shares one mint between concurrent callers", async () => {
    const { session, createVisitorSession } = setup();
    const [a, b] = await Promise.all([session.ensureToken(), session.ensureToken()]);
    expect(a).toBe(b);
    expect(createVisitorSession).toHaveBeenCalledTimes(1);
    expect(await session.ensureToken()).toBe(a);
    expect(createVisitorSession).toHaveBeenCalledTimes(1);
  });

  it("rotates silently with the previous token when it is near or past expiry", async () => {
    const { session, createVisitorSession, solve, advance } = setup();
    await session.ensureToken();
    advance(900 * 1000 - 5_000); // inside the 30 s margin
    const rotated = await session.ensureToken();
    expect(rotated).toBe("tok-2-rot");
    expect(createVisitorSession).toHaveBeenLastCalledWith({ previousToken: "tok-1-pow" });
    expect(solve).toHaveBeenCalledTimes(1);
  });

  it("falls back to a new proof of work when rotation is rejected as stale", async () => {
    const { session, createVisitorSession, solve, advance } = setup();
    await session.ensureToken();
    advance(20 * 60 * 1000);
    createVisitorSession.mockImplementationOnce(async () => {
      throw rejected(401);
    });
    const token = await session.ensureToken();
    expect(token).toBe("tok-3-pow");
    expect(solve).toHaveBeenCalledTimes(2);
    // The visitor id is carried over so continuity survives the re-challenge.
    expect(createVisitorSession).toHaveBeenLastCalledWith({
      altcha: "payload",
      visitorId: "visitor-1"
    });
  });

  it("does not rotate a token that is past the grace window", async () => {
    const { session, createVisitorSession, solve, advance } = setup();
    await session.ensureToken();
    advance(3 * 60 * 60 * 1000);
    expect(session.hasIdentity).toBe(false);
    await session.ensureToken();
    expect(createVisitorSession).toHaveBeenLastCalledWith({
      altcha: "payload",
      visitorId: "visitor-1"
    });
    expect(solve).toHaveBeenCalledTimes(2);
  });

  it("skips the challenge when the widget has bot protection off", async () => {
    const { session, createVisitorSession, solve } = setup({ botProtection: "none" });
    await session.ensureToken();
    expect(solve).not.toHaveBeenCalled();
    expect(createVisitorSession).toHaveBeenCalledWith({ visitorId: undefined });
  });

  it("restores a remembered session from storage and can be invalidated", async () => {
    const storage = new MemoryStorage();
    const first = setup({ storage });
    await first.session.ensureToken();
    first.session.rememberSession("sess-1");

    const second = setup({ storage });
    expect(second.session.sessionId).toBe("sess-1");
    expect(second.session.visitorId).toBe("visitor-1");
    expect(second.session.hasIdentity).toBe(true);

    second.session.invalidate();
    expect(second.session.token).toBe("");
    expect(second.session.hasIdentity).toBe(false);
    expect(second.session.sessionId).toBe("sess-1");
    await second.session.ensureToken();
    expect(second.createVisitorSession).toHaveBeenCalledWith({
      altcha: "payload",
      visitorId: "visitor-1"
    });

    second.session.clear();
    expect(storage.store.size).toBe(0);
  });

  it("survives corrupt storage", () => {
    const storage = new MemoryStorage();
    storage.setItem(storageKey("wgt_x"), "{not json");
    const { session } = setup({ storage });
    expect(session.token).toBeNull();
  });
});
