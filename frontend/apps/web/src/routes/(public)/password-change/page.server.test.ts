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
    discoverLocalPasswordState: vi.fn(),
    discoverPasswordChangeCapability: vi.fn(),
    RequestError
  };
});

vi.mock("$lib/features/auth/auth.server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/features/auth/auth.server")>()),
  clearFrontendCookies: mocks.clearFrontendCookies
}));
vi.mock("$lib/features/auth/passwordChange.server", () => ({
  changePassword: mocks.changePassword,
  discoverLocalPasswordState: mocks.discoverLocalPasswordState,
  discoverPasswordChangeCapability: mocks.discoverPasswordChangeCapability,
  PasswordChangeRequestError: mocks.RequestError
}));

import { resolveSafeLoginDestination } from "$lib/features/auth/auth.server";
import { actions, load } from "./+page.server";

const capability = {
  source: "eneo" as const,
  policy: {
    minLength: 12,
    maxBytes: 72,
    requiresUppercase: false,
    requiresLowercase: false,
    requiresNumber: false,
    requiresSymbol: false
  }
};

function event(url: string, token: string | null = "eneo-token", body?: FormData) {
  return {
    url: new URL(url),
    request: new Request(url, body ? { method: "POST", body } : undefined),
    fetch: vi.fn(),
    cookies: { getAll: vi.fn(() => []), delete: vi.fn() },
    locals: {
      id_token: token,
      access_token: null,
      environment: { baseUrl: "https://api.example", authUrl: undefined }
    }
  };
}

async function redirectFrom(outcome: unknown) {
  try {
    await outcome;
  } catch (error) {
    return error as { status: number; location: string };
  }
  throw new Error("expected a redirect");
}

describe("forced password change page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.discoverLocalPasswordState.mockResolvedValue({
      capability,
      changeReason: "admin_set",
      username: "person"
    });
    mocks.discoverPasswordChangeCapability.mockResolvedValue(capability);
    mocks.changePassword.mockResolvedValue("complete");
  });

  test("sends a signed-out visitor to login and back here afterwards", async () => {
    const redirect = await redirectFrom(
      load(event("https://eneo.example/password-change?next=%2Fspaces", null) as never)
    );
    expect(redirect.status).toBe(302);
    expect(redirect.location).toBe("/login?next=%2Fpassword-change%3Fnext%3D%252Fspaces");
    expect(mocks.discoverLocalPasswordState).not.toHaveBeenCalled();
  });

  test("shows the form with the reason when a change is required", async () => {
    const result = await load(
      event("https://eneo.example/password-change?next=%2Fspaces%2Fabc") as never
    );
    expect(result).toEqual({
      capability,
      reason: "admin_set",
      username: "person",
      next: "/spaces/abc"
    });
  });

  test("leaves for the requested page when nothing needs changing, never to another site", async () => {
    mocks.discoverLocalPasswordState.mockResolvedValue({
      capability,
      changeReason: null,
      username: "person"
    });
    const redirect = await redirectFrom(
      load(event("https://eneo.example/password-change?next=https%3A%2F%2Fevil.example") as never)
    );
    expect(redirect.status).toBe(302);
    expect(redirect.location).toBe(resolveSafeLoginDestination(null));
    expect(redirect.location).not.toContain("evil.example");
  });

  test("an unreadable account state shows the unavailable notice instead of leaving", async () => {
    mocks.discoverLocalPasswordState.mockResolvedValue({
      capability: { source: "unavailable", policy: null },
      changeReason: null,
      username: null
    });
    const data = await load(event("https://eneo.example/password-change?next=%2Fspaces") as never);
    expect(data).toMatchObject({
      capability: { source: "unavailable" },
      reason: null,
      next: "/spaces"
    });
  });

  test("a successful change signs this browser out and carries the destination to login", async () => {
    const form = new FormData();
    form.set("currentPassword", "one-time password");
    form.set("newPassword", "a sufficiently long new secret");
    form.set("confirmPassword", "a sufficiently long new secret");
    const redirect = await redirectFrom(
      actions.changePassword(
        event(
          "https://eneo.example/password-change?/changePassword&next=%2Fspaces",
          "t",
          form
        ) as never
      )
    );
    expect(mocks.changePassword).toHaveBeenCalledWith(
      expect.anything(),
      capability,
      "one-time password",
      "a sufficiently long new secret"
    );
    expect(mocks.clearFrontendCookies).toHaveBeenCalledTimes(1);
    expect(redirect.status).toBe(303);
    expect(redirect.location).toBe("/login?message=password_changed&next=%2Fspaces");
  });

  test("the change targets the local password even when a provider token is present", async () => {
    mocks.discoverPasswordChangeCapability.mockResolvedValue({
      source: "zitadel",
      policy: capability.policy
    });
    const form = new FormData();
    form.set("currentPassword", "one-time password");
    form.set("newPassword", "a sufficiently long new secret");
    form.set("confirmPassword", "a sufficiently long new secret");
    await redirectFrom(
      actions.changePassword(
        event("https://eneo.example/password-change?/changePassword", "t", form) as never
      )
    );
    expect(mocks.discoverPasswordChangeCapability).not.toHaveBeenCalled();
    expect(mocks.changePassword).toHaveBeenCalledWith(
      expect.anything(),
      capability,
      "one-time password",
      "a sufficiently long new secret"
    );
  });

  test("a wrong one-time password is reported on the current-password field", async () => {
    mocks.changePassword.mockRejectedValue(
      new mocks.RequestError("current_password_incorrect", 400)
    );
    const form = new FormData();
    form.set("currentPassword", "wrong");
    form.set("newPassword", "a sufficiently long new secret");
    form.set("confirmPassword", "a sufficiently long new secret");
    const result = (await actions.changePassword(
      event("https://eneo.example/password-change?/changePassword", "t", form) as never
    )) as { status: number; data: { passwordChange: unknown } };
    expect(result.status).toBe(400);
    expect(result.data.passwordChange).toEqual({
      fieldErrors: { currentPassword: "current_password_incorrect" }
    });
    expect(mocks.clearFrontendCookies).not.toHaveBeenCalled();
  });
});
