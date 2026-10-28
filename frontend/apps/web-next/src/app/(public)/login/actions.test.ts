import { beforeEach, expect, it, vi } from "vitest";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
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

function login(next?: string) {
  const form = new FormData();
  form.set("email", "anna@kommun.se");
  form.set("password", "rätt-lösenord");
  if (next !== undefined) form.set("next", next);
  return loginAction({}, form);
}

beforeEach(() => {
  vi.clearAllMocks();
  passwordLogin.mockResolvedValue({ ok: true, session: { mode: "password" } });
});

// A server action's redirect() is a client-side navigation: the previous
// session's query cache would render on the new user's first page.
it("hands the page it continues to back to the form instead of redirecting", async () => {
  expect(await login("/spaces/abc?tab=files")).toEqual({ redirectTo: "/spaces/abc?tab=files" });
  expect(setSessionCookie).toHaveBeenCalledWith({ mode: "password" });
  expect(redirect).not.toHaveBeenCalled();
});

it("continues to the landing page when the next page is missing or not this app's", async () => {
  expect(await login()).toEqual({ redirectTo: DEFAULT_LANDING });
  expect(await login("//evil.example/spaces")).toEqual({ redirectTo: DEFAULT_LANDING });
});
