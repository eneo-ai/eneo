import { beforeEach, describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => {
  class RequestError extends Error {
    constructor(
      readonly reason: string,
      readonly status: number
    ) {
      super(reason);
    }
  }

  return {
    changePassword: vi.fn(),
    clearFrontendCookies: vi.fn(),
    discoverPasswordChangeCapability: vi.fn(),
    RequestError
  };
});

vi.mock("$lib/features/auth/auth.server", () => ({
  clearFrontendCookies: mocks.clearFrontendCookies
}));
vi.mock("$lib/features/auth/passwordChange.server", () => ({
  changePassword: mocks.changePassword,
  discoverPasswordChangeCapability: mocks.discoverPasswordChangeCapability,
  PasswordChangeRequestError: mocks.RequestError
}));

import { actions } from "./+page.server";

const capability = {
  source: "eneo" as const,
  policy: {
    minLength: 15,
    maxBytes: 72,
    requiresUppercase: false,
    requiresLowercase: false,
    requiresNumber: false,
    requiresSymbol: false
  }
};

function eventWithPasswords(current: string, next: string, confirmation: string) {
  const form = new FormData();
  form.set("currentPassword", current);
  form.set("newPassword", next);
  form.set("confirmPassword", confirmation);
  return {
    request: new Request("https://eneo.example/account?/changePassword", {
      method: "POST",
      body: form
    }),
    fetch: vi.fn(),
    cookies: { getAll: vi.fn(() => []), delete: vi.fn() },
    locals: {
      id_token: "eneo-token",
      access_token: null,
      environment: {
        baseUrl: "https://api.example",
        authUrl: "https://identity.example"
      }
    }
  };
}

describe("account password action", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.discoverPasswordChangeCapability.mockResolvedValue(capability);
    mocks.changePassword.mockResolvedValue("complete");
  });

  test("rejects a mistyped confirmation without returning either password", async () => {
    const event = eventWithPasswords(
      "current secret",
      "a sufficiently long new secret",
      "a sufficiently long new secreu"
    );

    const result = await actions.changePassword!(event as never);

    expect(result).toMatchObject({
      status: 400,
      data: {
        passwordChange: {
          fieldErrors: { confirmPassword: "confirmation_mismatch" }
        }
      }
    });
    expect(JSON.stringify(result)).not.toContain("current secret");
    expect(JSON.stringify(result)).not.toContain("sufficiently long");
    expect(mocks.changePassword).not.toHaveBeenCalled();
  });

  test("clears cookies and redirects after a successful change", async () => {
    const event = eventWithPasswords(
      "current secret",
      "a sufficiently long new secret",
      "a sufficiently long new secret"
    );

    await expect(actions.changePassword!(event as never)).rejects.toMatchObject({
      status: 303,
      location: "/login?message=password_changed"
    });
    expect(mocks.clearFrontendCookies).toHaveBeenCalledWith(event);
  });

  test("surfaces the non-rollbackable session invalidation failure as partial success", async () => {
    mocks.changePassword.mockResolvedValue("session_invalidation_failed");
    const event = eventWithPasswords(
      "current secret",
      "a sufficiently long new secret",
      "a sufficiently long new secret"
    );

    await expect(actions.changePassword!(event as never)).rejects.toMatchObject({
      status: 303,
      location: "/login?message=password_changed_sessions_remain"
    });
    expect(mocks.clearFrontendCookies).toHaveBeenCalledWith(event);
  });

  test("maps a stable incorrect-current error to the current field", async () => {
    mocks.changePassword.mockRejectedValue(
      new mocks.RequestError("current_password_incorrect", 400)
    );
    const event = eventWithPasswords(
      "wrong current",
      "a sufficiently long new secret",
      "a sufficiently long new secret"
    );

    await expect(actions.changePassword!(event as never)).resolves.toMatchObject({
      status: 400,
      data: {
        passwordChange: {
          fieldErrors: { currentPassword: "current_password_incorrect" }
        }
      }
    });
  });
});
