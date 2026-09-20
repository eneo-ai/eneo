import { describe, expect, test, vi } from "vitest";
import { createZitadelClient, ZitadelRequestError } from "./Zitadel";

const BASE_URL = "https://identity.example";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("Zitadel password ownership", () => {
  test("requires both a human password and an enabled username/password login policy", async () => {
    const fetchFn = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          user: {
            human: { passwordChanged: "2026-08-27T08:30:00Z" }
          }
        })
      )
      .mockResolvedValueOnce(jsonResponse({ policy: { allowUsernamePassword: true } }))
      .mockResolvedValueOnce(
        jsonResponse({
          policy: {
            minLength: "12",
            hasUppercase: true,
            hasLowercase: true,
            hasNumber: true,
            hasSymbol: false
          }
        })
      );

    const client = createZitadelClient(BASE_URL, "provider-token", fetchFn);

    await expect(client.getPasswordChangeCapability()).resolves.toEqual({
      source: "zitadel",
      policy: {
        minLength: 12,
        hasUppercase: true,
        hasLowercase: true,
        hasNumber: true,
        hasSymbol: false
      }
    });
    expect(fetchFn.mock.calls.map(([request]) => String(request))).toEqual([
      `${BASE_URL}/auth/v1/users/me`,
      `${BASE_URL}/auth/v1/policies/login`,
      `${BASE_URL}/auth/v1/policies/passwords/complexity`
    ]);
    for (const [, init] of fetchFn.mock.calls) {
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer provider-token");
    }
  });

  test("classifies a human without a local password as externally managed", async () => {
    const fetchFn = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ user: { human: {} } }))
      .mockResolvedValueOnce(jsonResponse({ policy: { allowUsernamePassword: true } }));

    const client = createZitadelClient(BASE_URL, "provider-token", fetchFn);

    await expect(client.getPasswordChangeCapability()).resolves.toEqual({
      source: "external",
      policy: null
    });
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  test.each([
    ["failed response", jsonResponse({}, 503)],
    ["malformed response", jsonResponse({ user: {} })]
  ])("fails closed for a %s", async (_name, userResponse) => {
    const fetchFn = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(userResponse)
      .mockResolvedValueOnce(jsonResponse({ policy: { allowUsernamePassword: true } }));
    const client = createZitadelClient(BASE_URL, "provider-token", fetchFn);

    await expect(client.getPasswordChangeCapability()).rejects.toBeInstanceOf(ZitadelRequestError);
  });

  test("updates the current user's password with Zitadel's self-service contract", async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ details: {} }));
    const client = createZitadelClient(`${BASE_URL}/`, "provider-token", fetchFn);

    await client.updatePassword("old secret", "new secret");

    expect(fetchFn).toHaveBeenCalledOnce();
    const [url, init] = fetchFn.mock.calls[0];
    expect(String(url)).toBe(`${BASE_URL}/auth/v1/users/me/password`);
    expect(init?.method).toBe("PUT");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(init?.body).toBe(
      JSON.stringify({ oldPassword: "old secret", newPassword: "new secret" })
    );
  });
});
