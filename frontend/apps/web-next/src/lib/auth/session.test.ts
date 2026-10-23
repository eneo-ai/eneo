import { afterEach, expect, it, vi } from "vitest";
import { env } from "@/lib/env";
import { sealSession } from "./session-codec";
import { getAccessTokenOrNull } from "./session";
const store = vi.hoisted(() => ({ get: vi.fn(), set: vi.fn() }));
const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/headers", () => ({ cookies: async () => store }));
vi.mock("./oidc", () => ({ refreshTokens: refresh }));
afterEach(() => vi.clearAllMocks());
it.each([30, -1])(
  "reads tokens without consuming refresh tokens in RSC: expiry %s",
  async (expiresIn) => {
    store.get.mockReturnValue({
      value: await sealSession(
        {
          mode: "oidc",
          accessToken: "access",
          accessTokenExpiresAt: Math.floor(Date.now() / 1000) + expiresIn,
          refreshToken: "rotate-once",
          user: { email: "anna@example.se" }
        },
        env.SESSION_SECRET,
        3600
      )
    });
    expect(await getAccessTokenOrNull()).toBe(expiresIn > 0 ? "access" : null);
    expect(refresh).not.toHaveBeenCalled();
    expect(store.set).not.toHaveBeenCalled();
  }
);
