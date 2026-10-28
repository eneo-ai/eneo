import { beforeEach, expect, it, vi } from "vitest";
import { loginAction } from "./actions";

const { passwordLogin, setSessionCookie, redirect } = vi.hoisted(() => ({
  passwordLogin: vi.fn(),
  setSessionCookie: vi.fn(),
  redirect: vi.fn(() => {
    throw new Error("NEXT_REDIRECT");
  })
}));
vi.mock("@/lib/auth/password", () => ({ passwordLogin }));
vi.mock("@/lib/auth/session", () => ({ setSessionCookie }));
vi.mock("next/navigation", () => ({ redirect }));

beforeEach(() => {
  vi.clearAllMocks();
  passwordLogin.mockResolvedValue({ ok: true, session: { mode: "password" } });
});

// A server action's redirect() is a client-side navigation: the previous
// session's query cache would render on the new user's first page. The login
// page, re-rendered with the new session cookie, continues in a new document.
it("sets the session and leaves the navigation to the login page", async () => {
  const form = new FormData();
  form.set("email", "anna@kommun.se");
  form.set("password", "rätt-lösenord");

  expect(await loginAction({}, form)).toEqual({});
  expect(setSessionCookie).toHaveBeenCalledWith({ mode: "password" });
  expect(redirect).not.toHaveBeenCalled();
});
