import { describe, expect, it } from "vitest";
import {
  needsRefresh,
  openSession,
  openTxn,
  REFRESH_LEEWAY_SECONDS,
  sealSession,
  sealTxn,
  type SessionPayload
} from "./session-codec";

const SECRET = "test-secret-that-is-at-least-32-chars!!";

const session: SessionPayload = {
  mode: "oidc",
  accessToken: "at-123",
  accessTokenExpiresAt: 2_000_000_000,
  refreshToken: "rt-456",
  idToken: "idt-789",
  user: { email: "user@example.com", name: "User" }
};

describe("session seal/open", () => {
  it("round-trips a session", async () => {
    const sealed = await sealSession(session, SECRET, 3600);
    expect(await openSession(sealed, SECRET)).toEqual(session);
  });

  it("rejects a tampered cookie", async () => {
    const sealed = await sealSession(session, SECRET, 3600);
    const tampered = sealed.slice(0, -4) + "AAAA";
    expect(await openSession(tampered, SECRET)).toBeNull();
  });

  it("rejects a cookie sealed with a different secret", async () => {
    const sealed = await sealSession(session, "another-secret-that-is-32-chars-long!!", 3600);
    expect(await openSession(sealed, SECRET)).toBeNull();
  });

  it("rejects an expired seal", async () => {
    const sealed = await sealSession(session, SECRET, -10);
    expect(await openSession(sealed, SECRET)).toBeNull();
  });

  it("rejects garbage", async () => {
    expect(await openSession("not-a-jwe", SECRET)).toBeNull();
  });
});

describe("txn seal/open", () => {
  it("round-trips an authorization transaction", async () => {
    const txn = { verifier: "v", state: "s", nonce: "n", next: "/spaces" };
    const sealed = await sealTxn(txn, SECRET, 600);
    expect(await openTxn(sealed, SECRET)).toEqual(txn);
  });

  it("does not open a session cookie as a txn", async () => {
    const sealed = await sealSession(session, SECRET, 3600);
    expect(await openTxn(sealed, SECRET)).toBeNull();
  });
});

describe("needsRefresh", () => {
  const expiresAt = 1_000_000;

  it("is false well before the leeway window", () => {
    expect(needsRefresh({ ...session, accessTokenExpiresAt: expiresAt }, expiresAt - 120)).toBe(
      false
    );
  });

  it("is true exactly at the leeway boundary", () => {
    expect(
      needsRefresh(
        { ...session, accessTokenExpiresAt: expiresAt },
        expiresAt - REFRESH_LEEWAY_SECONDS
      )
    ).toBe(true);
  });

  it("is true after expiry", () => {
    expect(needsRefresh({ ...session, accessTokenExpiresAt: expiresAt }, expiresAt + 1)).toBe(true);
  });
});
