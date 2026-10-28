import { describe, expect, it } from "vitest";
import { DEFAULT_LANDING, safeNextPath } from "./safe-next";

describe("safeNextPath", () => {
  it("keeps same-origin absolute paths", () => {
    expect(safeNextPath("/dashboard")).toBe("/dashboard");
    expect(safeNextPath("/spaces/personal/chat?tab=chat")).toBe("/spaces/personal/chat?tab=chat");
    expect(safeNextPath("/")).toBe("/");
  });

  it("rejects protocol-relative and backslash tricks (open redirect)", () => {
    expect(safeNextPath("//evil.com")).toBe(DEFAULT_LANDING);
    expect(safeNextPath("/\\evil.com")).toBe(DEFAULT_LANDING);
  });

  it("rejects absolute URLs and non-paths", () => {
    expect(safeNextPath("https://evil.com")).toBe(DEFAULT_LANDING);
    expect(safeNextPath("evil.com")).toBe(DEFAULT_LANDING);
  });

  it.each([
    "/\n/evil.example",
    "/\t/evil.example",
    "/%2fexample.com",
    "/%5cexample.com",
    "/bad%escape",
    "/ok\u007f"
  ])("rejects ambiguous browser destinations: %s", (value) =>
    expect(safeNextPath(value)).toBe(DEFAULT_LANDING)
  );

  // A sign-in continues through /login (signedInContinuation): next=/login
  // would nest it, and /login/switch-organisation or /logout would end the new
  // session (an auth redirect loop).
  it.each([
    "/login",
    "/login?next=%2Fdashboard",
    "/login/switch-organisation",
    "/login/../login",
    "/logout",
    "/logout?reason=expired"
  ])("never continues to the login or logout pages: %s", (value) =>
    expect(safeNextPath(value)).toBe(DEFAULT_LANDING)
  );

  // The continuation is a same-origin navigation: to a route handler it would
  // carry Sec-Fetch-Site: same-origin past the browser-session gate.
  it.each([
    "/api",
    "/api/eneo/api/v1/users/me/",
    "/api/v1/users/me/",
    "/api/chat",
    "/auth/login",
    "/auth/callback?code=x&state=y",
    "/_next/static/chunks/main.js",
    "/spaces/../api/v1/users/me/",
    "/%61pi/v1/users/me/",
    // Dot segments that leave an empty segment, which servers merge.
    "/.//api/v1/users/me/",
    "/x/..//api/v1/",
    "/%2e//logout",
    "/.%2F/api/v1",
    "/.//login",
    "/a/%2F../api/v1/",
    // An encoded ? or # before a dot segment: only the decoded parsed path shows /api.
    "/%3F/../%61pi/v1/users/me/",
    "/%23/../%61pi/v1/users/me/",
    "/%3F/../%6Cogout",
    // Only the parsed path shows /api (the decoded value parses back to /spaces).
    "/api/x%2F..%2F..%2Fspaces",
    "/logout%2F..%2Fspaces",
    // Only the parsed decoded value shows /api (a server that decodes, then
    // resolves dot segments).
    "/x/%2E%2E%2Fapi/v1/users/me/"
  ])("never continues to a route that is not a page: %s", (value) =>
    expect(safeNextPath(value)).toBe(DEFAULT_LANDING)
  );

  it.each(["/apis", "/authors", "/spaces/api", "/module-login?state=x"])(
    "keeps pages that only share a prefix: %s",
    (value) => expect(safeNextPath(value)).toBe(value)
  );

  it("preserves opaque query encoding after validation", () => {
    const next = "/module-login?state=a%2Bb%252Fc";
    expect(safeNextPath(next)).toBe(next);
  });

  it("falls back for empty / nullish", () => {
    expect(safeNextPath("")).toBe(DEFAULT_LANDING);
    expect(safeNextPath(null)).toBe(DEFAULT_LANDING);
    expect(safeNextPath(undefined)).toBe(DEFAULT_LANDING);
  });
});
