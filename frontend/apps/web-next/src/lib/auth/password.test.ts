import { describe, expect, it } from "vitest";
import { sessionFromEneoJwt } from "./password";

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
