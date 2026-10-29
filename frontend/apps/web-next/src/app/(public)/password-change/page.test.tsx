import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/session", () => ({
  getAccessTokenOrNull: async () => "session-revoked-by-backend"
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key
}));
const { ChangePasswordForm } = vi.hoisted(() => ({ ChangePasswordForm: vi.fn(() => null) }));
vi.mock("@/features/account/change-password", () => ({ ChangePasswordForm }));

import PasswordChangePage from "./page";

afterEach(() => {
  vi.unstubAllGlobals();
  ChangePasswordForm.mockClear();
});

function me(changeRequired: boolean, reason: "admin_set" | "expired" = "admin_set") {
  return new Response(
    JSON.stringify({
      email: "person@example.com",
      password_change: {
        source: "eneo",
        policy: {
          min_length: 7,
          max_bytes: 72,
          requires_uppercase: false,
          requires_lowercase: false,
          requires_number: false,
          requires_symbol: false
        }
      },
      password_status: changeRequired
        ? { change_required: true, reason }
        : { change_required: false, reason: null }
    }),
    { status: 200, headers: { "content-type": "application/json" } }
  );
}

/** Renders the page and returns the props the form was given. */
async function renderForm(next?: string, reason?: "admin_set" | "expired") {
  vi.stubGlobal("fetch", async () => me(true, reason));
  const page = await PasswordChangePage({ searchParams: Promise.resolve({ next }) });
  const form = page.props.children;
  expect(form.type).toBe(ChangePasswordForm);
  return form.props as { afterChangeHref: string; currentPasswordHint: string };
}

describe("password-change session recovery", () => {
  it("redirects a backend-rejected session through logout instead of swallowing the redirect", async () => {
    vi.stubGlobal("fetch", async () => new Response(null, { status: 401 }));
    await expect(PasswordChangePage({ searchParams: Promise.resolve({}) })).rejects.toMatchObject({
      digest: expect.stringContaining("/logout?reason=expired")
    });
  });

  it("sends a session that needs no change on to the requested page, never off-site", async () => {
    vi.stubGlobal("fetch", async () => me(false));
    await expect(
      PasswordChangePage({ searchParams: Promise.resolve({ next: "/spaces/abc" }) })
    ).rejects.toMatchObject({ digest: expect.stringContaining(";/spaces/abc;") });
    await expect(
      PasswordChangePage({ searchParams: Promise.resolve({ next: "https://evil.example" }) })
    ).rejects.toMatchObject({ digest: expect.stringContaining(";/spaces/personal/chat;") });
  });

  it("after the change, signs out with the notice and keeps the requested page", async () => {
    expect((await renderForm("/spaces/abc")).afterChangeHref).toBe(
      "/logout?reason=password_changed&next=%2Fspaces%2Fabc"
    );
    expect((await renderForm("//evil.example")).afterChangeHref).toBe(
      "/logout?reason=password_changed"
    );
  });

  it("asks for the password just used only when it was one-time", async () => {
    expect((await renderForm(undefined, "admin_set")).currentPasswordHint).toBe(
      "password_change_required_current_hint"
    );
    expect((await renderForm(undefined, "expired")).currentPasswordHint).toBe(
      "password_change_required_expired_current_hint"
    );
  });

  it("still renders the unavailable message when the backend cannot be reached", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("fetch failed");
    });
    const page = await PasswordChangePage({ searchParams: Promise.resolve({}) });
    expect(page.props.children.props.children).toBe("password_change_not_available");
  });
});
