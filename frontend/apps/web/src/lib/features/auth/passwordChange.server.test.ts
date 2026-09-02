import { afterEach, describe, expect, test, vi } from "vitest";
import {
  changePassword,
  discoverPasswordChangeCapability,
  PasswordChangeRequestError
} from "./passwordChange.server";
import { ENEO_PASSWORD_POLICY } from "./passwordChange";

const context = {
  backendUrl: "https://api.example",
  eneoToken: "eneo-token",
  zitadelUrl: "https://identity.example",
  zitadelToken: null,
  fetch: vi.fn<typeof fetch>()
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("password change server adapter", () => {
  test("reads the local capability from the authenticated self response", async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        password_change: {
          source: "eneo",
          policy: { min_length: 15, max_bytes: 72 }
        }
      })
    );

    await expect(discoverPasswordChangeCapability({ ...context, fetch: fetchFn })).resolves.toEqual(
      { source: "eneo", policy: ENEO_PASSWORD_POLICY }
    );
    expect(fetchFn).toHaveBeenCalledWith(
      "https://api.example/api/v1/users/me/",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({ Authorization: "Bearer eneo-token" })
      })
    );
  });

  test("does not fall back to an Eneo password when provider discovery fails", async () => {
    const fetchFn = vi.fn<typeof fetch>().mockImplementation(async (request) => {
      const url = String(request);
      if (url.startsWith("https://identity.example/")) return jsonResponse({}, 503);
      return jsonResponse({
        password_change: {
          source: "eneo",
          policy: { min_length: 15, max_bytes: 72 }
        }
      });
    });

    await expect(
      discoverPasswordChangeCapability({
        ...context,
        zitadelToken: "provider-token",
        fetch: fetchFn
      })
    ).resolves.toEqual({ source: "unavailable", policy: null });
    expect(
      fetchFn.mock.calls.some(([request]) => String(request).startsWith("https://api.example"))
    ).toBe(false);
  });

  test("sends local passwords only through the server-only direct fetch boundary", async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }));

    await expect(
      changePassword(
        { ...context, fetch: fetchFn },
        { source: "eneo", policy: ENEO_PASSWORD_POLICY },
        "current secret",
        "a sufficiently long new secret"
      )
    ).resolves.toBe("complete");

    const [url, init] = fetchFn.mock.calls[0];
    expect(String(url)).toBe("https://api.example/api/v1/users/me/password/");
    expect(init?.body).toBe(
      JSON.stringify({
        current_password: "current secret",
        new_password: "a sufficiently long new secret"
      })
    );
  });

  test("throws a sanitized stable reason without retaining password payloads", async () => {
    const fetchFn = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ eneo_error_code: 9057, message: "wrong" }, 400));

    let thrown: unknown;
    try {
      await changePassword(
        { ...context, fetch: fetchFn },
        { source: "eneo", policy: ENEO_PASSWORD_POLICY },
        "do-not-retain-current",
        "do-not-retain-new-password"
      );
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(PasswordChangeRequestError);
    expect(thrown).toMatchObject({ reason: "current_password_incorrect", status: 400 });
    expect(JSON.stringify(thrown)).not.toContain("do-not-retain");
    expect(String(thrown)).not.toContain("do-not-retain");
  });

  test("classifies the structured limiter response without retaining its body", async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          detail: { code: "rate_limit_exceeded", message: "sensitive upstream detail" }
        },
        429
      )
    );

    await expect(
      changePassword(
        { ...context, fetch: fetchFn },
        { source: "eneo", policy: ENEO_PASSWORD_POLICY },
        "current secret",
        "a sufficiently long new secret"
      )
    ).rejects.toMatchObject({ reason: "rate_limited", status: 429 });
  });

  test("maps a Zitadel 429 to the same typed rate-limit failure", async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({}, 429));

    await expect(
      changePassword(
        {
          ...context,
          zitadelToken: "provider-token",
          fetch: fetchFn
        },
        {
          source: "zitadel",
          policy: {
            minLength: 10,
            maxBytes: null,
            requiresUppercase: false,
            requiresLowercase: false,
            requiresNumber: false,
            requiresSymbol: false
          }
        },
        "provider old",
        "provider new password"
      )
    ).rejects.toMatchObject({ reason: "rate_limited", status: 429 });
    expect(fetchFn).toHaveBeenCalledOnce();
  });

  test("reports partial success when Zitadel changed but Eneo invalidation failed", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchFn = vi.fn<typeof fetch>().mockImplementation(async (request, init) => {
      const url = String(request);
      if (url.endsWith("/auth/v1/users/me/password")) {
        expect(init?.body).toBe(
          JSON.stringify({ oldPassword: "provider old", newPassword: "Provider new!1" })
        );
        return jsonResponse({ details: {} });
      }
      if (url.endsWith("/api/v1/users/me/sessions/invalidate/")) {
        return jsonResponse({}, 503);
      }
      throw new Error(`Unexpected test request: ${url}`);
    });

    await expect(
      changePassword(
        {
          ...context,
          zitadelToken: "provider-token",
          fetch: fetchFn
        },
        {
          source: "zitadel",
          policy: {
            minLength: 10,
            maxBytes: null,
            requiresUppercase: true,
            requiresLowercase: true,
            requiresNumber: true,
            requiresSymbol: true
          }
        },
        "provider old",
        "Provider new!1"
      )
    ).resolves.toBe("session_invalidation_failed");
  });
});
