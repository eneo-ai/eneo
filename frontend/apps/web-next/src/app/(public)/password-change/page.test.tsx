import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/session", () => ({
  getAccessTokenOrNull: async () => "session-revoked-by-backend"
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key
}));
vi.mock("@/app/(app)/account/change-password.client", () => ({
  ChangePasswordForm: () => null
}));

import PasswordChangePage from "./page";

afterEach(() => vi.unstubAllGlobals());

describe("password-change session recovery", () => {
  it("redirects a backend-rejected session through logout instead of swallowing the redirect", async () => {
    vi.stubGlobal("fetch", async () => new Response(null, { status: 401 }));
    await expect(PasswordChangePage({ searchParams: Promise.resolve({}) })).rejects.toMatchObject({
      digest: expect.stringContaining("/logout?reason=expired")
    });
  });

  it("still renders the unavailable message when the backend cannot be reached", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("fetch failed");
    });
    const page = await PasswordChangePage({ searchParams: Promise.resolve({}) });
    expect(page.props.children.props.children).toBe("password_change_not_available");
  });
});
