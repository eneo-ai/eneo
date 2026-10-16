import { afterAll, afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/env", () => ({ env: { ENEO_BACKEND_URL: "https://backend.example" } }));

import { passwordLogin, sessionFromEneoJwt } from "./password";

function fakeJwt(payload: Record<string, unknown>): string {
  const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode(payload)}.signature`;
}

describe("sessionFromEneoJwt", () => {
  it("builds a password session from sub and exp", () => {
    const session = sessionFromEneoJwt(fakeJwt({ sub: "user@example.com", exp: 2_000_000_000 }));
    expect(session).toEqual({
      mode: "password",
      accessToken: expect.any(String),
      accessTokenExpiresAt: 2_000_000_000,
      user: { email: "user@example.com" }
    });
  });

  it("returns null when sub is missing", () => {
    expect(sessionFromEneoJwt(fakeJwt({ exp: 2_000_000_000 }))).toBeNull();
  });

  it("returns null when exp is missing", () => {
    expect(sessionFromEneoJwt(fakeJwt({ sub: "user@example.com" }))).toBeNull();
  });

  it("returns null for a non-JWT", () => {
    expect(sessionFromEneoJwt("garbage")).toBeNull();
  });
});

describe("passwordLogin", () => {
  const fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchMock);

  afterEach(() => fetchMock.mockReset());
  afterAll(() => vi.unstubAllGlobals());

  const respond = (status: number, body: unknown) =>
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" }
      })
    );

  it("reports the attempts left after a wrong password", async () => {
    respond(401, { message: "Invalid credentials", attempts_remaining: 3 });

    await expect(passwordLogin("anna@kommun.se", "fel")).resolves.toEqual({
      ok: false,
      error: "invalid_credentials",
      limit: { attemptsRemaining: 3, retryAfterSeconds: null }
    });
  });

  it("reports how long the account is blocked when the backend refuses the attempt", async () => {
    respond(429, {
      message: "Too many failed login attempts.",
      attempts_remaining: 0,
      retry_after_seconds: 540
    });

    await expect(passwordLogin("anna@kommun.se", "fel")).resolves.toEqual({
      ok: false,
      error: "too_many_attempts",
      limit: { attemptsRemaining: 0, retryAfterSeconds: 540 }
    });
  });

  it("reports no standing when the backend did not count the attempt", async () => {
    respond(401, { message: "Invalid credentials", attempts_remaining: "3" });

    await expect(passwordLogin("anna@kommun.se", "fel")).resolves.toEqual({
      ok: false,
      error: "invalid_credentials",
      limit: { attemptsRemaining: null, retryAfterSeconds: null }
    });
  });

  it("tolerates a refusal without a JSON body", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 401 }));

    await expect(passwordLogin("anna@kommun.se", "fel")).resolves.toEqual({
      ok: false,
      error: "invalid_credentials",
      limit: { attemptsRemaining: null, retryAfterSeconds: null }
    });
  });

  it("signs in with the backend's token", async () => {
    respond(200, { access_token: fakeJwt({ sub: "anna@kommun.se", exp: 2_000_000_000 }) });

    await expect(passwordLogin("anna@kommun.se", "rätt")).resolves.toMatchObject({
      ok: true,
      session: { user: { email: "anna@kommun.se" } }
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://backend.example/api/v1/users/login/token/",
      expect.objectContaining({ method: "POST" })
    );
  });
});
