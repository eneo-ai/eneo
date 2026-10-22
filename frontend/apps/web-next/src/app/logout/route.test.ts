import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";

const { getSession, buildLogoutUrl, isOidcEnabled } = vi.hoisted(() => ({
  getSession: vi.fn(),
  buildLogoutUrl: vi.fn(),
  isOidcEnabled: vi.fn()
}));
vi.mock("@/lib/env", () => ({ env: { APP_ORIGIN: "https://app.example" } }));
vi.mock("@/lib/auth/session", () => ({ getSession, SESSION_COOKIE: "eneo_session" }));
vi.mock("@/lib/auth/oidc", () => ({ buildLogoutUrl, isOidcEnabled }));

function logout(query = "") {
  return GET(new NextRequest(`https://app.example/logout${query}`));
}

beforeEach(() => {
  vi.clearAllMocks();
  getSession.mockResolvedValue({ mode: "password" });
  isOidcEnabled.mockReturnValue(false);
});

describe("logout route", () => {
  it("tells the login page the password was changed and keeps the destination", async () => {
    const response = await logout("?reason=password_changed&next=%2Fspaces%2Fabc");
    expect(response.headers.get("location")).toBe(
      "https://app.example/login?message=password_changed&next=%2Fspaces%2Fabc"
    );
  });

  it("drops a destination that would leave the site", async () => {
    const response = await logout("?reason=password_changed&next=https%3A%2F%2Fevil.example");
    expect(response.headers.get("location")).toBe(
      "https://app.example/login?message=password_changed"
    );
  });

  it("treats an unknown reason as a plain logout and ignores next", async () => {
    const response = await logout("?reason=whatever&next=%2Fspaces%2Fabc");
    expect(response.headers.get("location")).toBe("https://app.example/login?message=logout");
  });

  it("skips the IdP logout when the session was ended by the backend or a password change", async () => {
    getSession.mockResolvedValue({ mode: "oidc", idToken: "id" });
    isOidcEnabled.mockReturnValue(true);
    buildLogoutUrl.mockResolvedValue("https://idp.example/end-session");

    expect((await logout("?reason=expired")).headers.get("location")).toBe(
      "https://app.example/login?message=expired"
    );
    expect((await logout("?reason=password_changed")).headers.get("location")).toBe(
      "https://app.example/login?message=password_changed"
    );
    expect((await logout()).headers.get("location")).toBe("https://idp.example/end-session");
    expect(buildLogoutUrl).toHaveBeenCalledTimes(1);
  });
});
