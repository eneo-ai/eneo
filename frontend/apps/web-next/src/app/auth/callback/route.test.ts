import { NextRequest } from "next/server";
import { beforeEach, expect, it, vi } from "vitest";
import { env } from "@/lib/env";
import { sealTxn } from "@/lib/auth/session-codec";
import { SESSION_COOKIE, TXN_COOKIE } from "@/lib/auth/session";
import { GET } from "./route";

const completeAuthorization = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth/oidc", () => ({ completeAuthorization }));

beforeEach(() => {
  completeAuthorization.mockResolvedValue({
    accessToken: "access",
    accessTokenExpiresAt: Math.floor(Date.now() / 1000) + 3600,
    refreshToken: "refresh",
    idToken: "id",
    claims: { email: "anna@example.se", name: "Anna Lind" }
  });
});

async function callback(next: string) {
  const txn = await sealTxn(
    { verifier: "verifier", state: "state", nonce: "nonce", next },
    env.SESSION_SECRET,
    600
  );
  return GET(
    new NextRequest("http://localhost:3100/auth/callback?code=code&state=state", {
      headers: { cookie: `${TXN_COOKIE}=${txn}` }
    })
  );
}

it("continues a sign-in through the login page, which loads it in a new document", async () => {
  const response = await callback("/spaces/list");

  expect(response.cookies.get(SESSION_COOKIE)?.value).toBeTruthy();
  expect(response.headers.get("location")).toBe(
    "http://localhost:3100/login?next=%2Fspaces%2Flist"
  );
});

it("keeps an unsafe next page out of the continuation", async () => {
  const response = await callback("//evil.example/spaces");

  expect(response.headers.get("location")).toBe(
    "http://localhost:3100/login?next=%2Fspaces%2Fpersonal%2Fchat"
  );
});
