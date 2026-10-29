import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { navigateTo } from "@/lib/navigate-to";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { submitPasswordLogin } from "./password-login";

vi.mock("@/lib/navigate-to", () => ({ navigateTo: vi.fn() }));
const fetchMock = vi.fn<typeof fetch>();
afterEach(() => vi.unstubAllGlobals());

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", fetchMock);
});

function credentials() {
  const form = new FormData();
  form.set("email", "user@example.test");
  form.set("password", "test-password");
  return form;
}

it("requires both credentials before making a request", async () => {
  expect(await submitPasswordLogin(undefined, {}, new FormData())).toEqual({
    error: "missing_fields",
    email: undefined
  });
  expect(fetchMock).not.toHaveBeenCalled();
});

it.each(["/admin?tab=users", "//evil.example"])(
  "posts the cookie login and finishes %s in a new document",
  async (next) => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    expect(await submitPasswordLogin(next, {}, credentials())).toEqual({});
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith("/api/v1/auth/session/password/", {
      method: "POST",
      credentials: "same-origin",
      redirect: "error",
      body: new URLSearchParams({ username: "user@example.test", password: "test-password" })
    });
    expect(navigateTo).toHaveBeenCalledExactlyOnceWith(
      next.startsWith("//") ? DEFAULT_LANDING : next
    );
  }
);

it.each([
  [401, "invalid_credentials"],
  [429, "too_many_attempts"]
])("retains the attempt limit after HTTP %s", async (status, error) => {
  fetchMock.mockResolvedValue(
    Response.json({ attempts_remaining: 2, retry_after_seconds: 65 }, { status: Number(status) })
  );
  expect(await submitPasswordLogin(undefined, {}, credentials())).toEqual({
    error,
    email: "user@example.test",
    attemptsRemaining: 2,
    retryAfterSeconds: 65
  });
  expect(navigateTo).not.toHaveBeenCalled();
});

it.each([
  [403, { eneo_error_code: 9019, message: "Disabled" }, "deactivated"],
  [403, { eneo_error_code: 9025, message: "Disabled" }, "deactivated"],
  [403, { code: "browser_origin_refused", message: "Refused" }, "unavailable"],
  [403, { message: "Forbidden" }, "unavailable"],
  [503, { message: "Unavailable" }, "unavailable"]
])("handles HTTP %s with %j without navigating", async (status, body, error) => {
  fetchMock.mockResolvedValue(Response.json(body, { status }));
  expect(await submitPasswordLogin(undefined, {}, credentials())).toEqual({
    error,
    email: "user@example.test"
  });
  expect(navigateTo).not.toHaveBeenCalled();
});

it("keeps a failed network attempt on the form", async () => {
  fetchMock.mockRejectedValue(new TypeError("Offline"));
  expect(await submitPasswordLogin(undefined, {}, credentials())).toEqual({
    error: "unavailable",
    email: "user@example.test"
  });
  expect(navigateTo).not.toHaveBeenCalled();
});
