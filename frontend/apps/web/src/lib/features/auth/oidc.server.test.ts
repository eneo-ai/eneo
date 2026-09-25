import { beforeEach, describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getBackendUrl: vi.fn(() => "https://eneo.example"),
  setFrontendAuthCookie: vi.fn()
}));

vi.mock("$lib/core/environment.server", () => ({
  getBackendUrl: mocks.getBackendUrl
}));

vi.mock("./auth.server", () => ({
  setFrontendAuthCookie: mocks.setFrontendAuthCookie
}));

import { loginWithOidc } from "./oidc.server";

describe("loginWithOidc", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getBackendUrl.mockReturnValue("https://eneo.example");
  });

  test("returns backend-validated frontend state without decoding it", async () => {
    const frontendState = '{"loginMethod":"oidc","next":"/module-login?state=a%2526b"}';
    const fetchFn = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "eneo-token",
          frontend_state: frontendState
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    const result = await loginWithOidc("code", "signed-backend-state", fetchFn);

    expect(result).toEqual({ frontendState });
    expect(mocks.setFrontendAuthCookie).toHaveBeenCalledWith({
      id_token: "eneo-token"
    });
    expect(fetchFn).toHaveBeenCalledOnce();
    const [, request] = fetchFn.mock.calls[0];
    expect(JSON.parse(request.body)).toEqual({
      code: "code",
      state: "signed-backend-state"
    });
  });

  test("keeps login compatible when an older backend omits frontend state", async () => {
    const fetchFn = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ access_token: "eneo-token" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(loginWithOidc("code", "state", fetchFn)).resolves.toEqual({
      frontendState: ""
    });
  });
});
