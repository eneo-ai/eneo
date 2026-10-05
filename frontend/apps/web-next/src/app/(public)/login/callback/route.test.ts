import { NextRequest } from "next/server";
import { beforeEach, expect, it, vi } from "vitest";
import { env } from "@/lib/env";
import { FEDERATION_TXN_COOKIE, openSession, sealFederationTxn } from "@/lib/auth/session-codec";
import { SESSION_COOKIE } from "@/lib/auth/session";
import { GET } from "./route";

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

it.each([undefined, "tampered"])(
  "rejects a callback without its browser transaction: %s",
  async (cookie) => {
    const response = await GET(
      new NextRequest("http://localhost:3100/login/callback?code=code&state=state", {
        headers: cookie ? { cookie: FEDERATION_TXN_COOKIE + "=" + cookie } : {}
      })
    );
    expect(new URL(response.headers.get("location")!).pathname).toBe("/login");
    expect(fetchMock).not.toHaveBeenCalled();
  }
);

it("rejects a transaction from a different login attempt before exchanging credentials", async () => {
  const cookie = await sealFederationTxn({ state: "original", next: "/" }, env.SESSION_SECRET);
  const response = await GET(
    new NextRequest("http://localhost:3100/login/callback?code=code&state=other", {
      headers: { cookie: FEDERATION_TXN_COOKIE + "=" + cookie }
    })
  );
  expect(response.cookies.has(SESSION_COOKIE)).toBe(false);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("establishes the same user's app session and consumes the matched transaction", async () => {
  const cookie = await sealFederationTxn(
    { state: "original", next: "/spaces/list" },
    env.SESSION_SECRET
  );
  const claims = Buffer.from(
    JSON.stringify({ sub: "anna@example.se", exp: Math.floor(Date.now() / 1000) + 3600 })
  ).toString("base64url");
  fetchMock.mockResolvedValue(Response.json({ access_token: "e30." + claims + ".signature" }));
  const response = await GET(
    new NextRequest("http://localhost:3100/login/callback?code=code&state=original", {
      headers: { cookie: FEDERATION_TXN_COOKIE + "=" + cookie }
    })
  );
  const session = await openSession(
    response.cookies.get(SESSION_COOKIE)!.value,
    env.SESSION_SECRET
  );
  expect(session?.user.email).toBe("anna@example.se");
  expect(response.cookies.get(FEDERATION_TXN_COOKIE)?.value).toBe("");
  expect(response.headers.get("location")).toBe("http://localhost:3100/spaces/list");
});
