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

import { LoginError } from "./LoginError";
import { loginWithOidc } from "./oidc.server";

const VERIFIER = "binding-verifier".padEnd(43, "0");

function refusal(status: number, code: string, message: string) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ message, eneo_error_code: 9000, code }), {
      status,
      headers: { "Content-Type": "application/json" }
    })
  );
}

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

    const result = await loginWithOidc("code", "signed-backend-state", VERIFIER, fetchFn);

    expect(result).toEqual({ frontendState });
    expect(mocks.setFrontendAuthCookie).toHaveBeenCalledWith({
      id_token: "eneo-token"
    });
    expect(fetchFn).toHaveBeenCalledOnce();
    const [, request] = fetchFn.mock.calls[0];
    expect(JSON.parse(request.body)).toEqual({
      code: "code",
      state: "signed-backend-state",
      binding_verifier: VERIFIER
    });
  });

  test("keeps login compatible when an older backend omits frontend state", async () => {
    const fetchFn = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ access_token: "eneo-token" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(loginWithOidc("code", "state", VERIFIER, fetchFn)).resolves.toEqual({
      frontendState: ""
    });
  });

  test("forwards the provider's iss parameter to the backend", async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ access_token: "eneo-token" }), { status: 200 })
      );

    await loginWithOidc("code", "state", VERIFIER, fetchFn, "https://idp.example");

    const [, request] = fetchFn.mock.calls[0];
    expect(JSON.parse(request.body)).toEqual({
      code: "code",
      state: "state",
      iss: "https://idp.example",
      binding_verifier: VERIFIER
    });
  });

  test.each([
    [503, "oidc_login_unavailable", "LOGIN_UNAVAILABLE"],
    [400, "oidc_transaction_invalid", "ATTEMPT_EXPIRED"],
    [401, "oidc_response_not_verified", "UNAUTHORIZED"],
    [403, "identity_conflict", "IDENTITY_CONFLICT"]
  ])("a typed %i refusal (%s) becomes %s", async (status, code, loginErrorCode) => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const error = await loginWithOidc(
      "code",
      "state",
      VERIFIER,
      refusal(status, code, "Refused.")
    ).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(LoginError);
    expect(error).toMatchObject({
      code: loginErrorCode,
      statusCode: status,
      rawDetail: "Refused."
    });
    expect(mocks.setFrontendAuthCookie).not.toHaveBeenCalled();
  });
});
