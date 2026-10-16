import { NextRequest } from "next/server";
import { beforeEach, expect, it, vi } from "vitest";
import { env } from "@/lib/env";
import { FEDERATION_TXN_COOKIE, openFederationTxn } from "@/lib/auth/session-codec";
import { GET } from "./route";

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

it("binds the exact backend state to this browser and selects this app's callback", async () => {
  fetchMock.mockResolvedValue(
    Response.json({ authorization_url: "https://idp.example/authorize", state: "signed-state" })
  );
  const response = await GET(
    new NextRequest("http://localhost:3100/api/auth/initiate?tenant=city&next=%2Fspaces%2Flist")
  );
  const target = new URL(fetchMock.mock.calls[0]![0]);
  expect(target.searchParams.get("redirect_uri")).toBe("http://localhost:3100/login/callback");
  expect(target.searchParams.get("tenant")).toBe("city");
  const cookie = response.cookies.get(FEDERATION_TXN_COOKIE);
  expect(cookie?.httpOnly).toBe(true);
  expect(await openFederationTxn(cookie!.value, env.SESSION_SECRET)).toEqual({
    state: "signed-state",
    next: "/spaces/list"
  });
  expect(response.headers.get("location")).toBe("https://idp.example/authorize");
});

it("supports single-tenant federation without choosing a different origin", async () => {
  fetchMock.mockResolvedValue(
    Response.json({ authorization_url: "https://idp.example/authorize", state: "signed-state" })
  );
  const response = await GET(new NextRequest("http://localhost:3100/api/auth/initiate"));
  expect(new URL(fetchMock.mock.calls[0]![0]).searchParams.has("tenant")).toBe(false);
  expect(response.cookies.has(FEDERATION_TXN_COOKIE)).toBe(true);
});

it("rejects invalid tenants before contacting the backend", async () => {
  expect(
    (await GET(new NextRequest("http://localhost:3100/api/auth/initiate?tenant=../other"))).status
  ).toBe(400);
  expect(fetchMock).not.toHaveBeenCalled();
});
