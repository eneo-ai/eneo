import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import "../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));
vi.mock("$lib/paraglide/runtime", () => ({ localizeHref: (href: string) => href }));

import LogoutPage from "./+page.svelte";

describe("logout page", () => {
  test("confirms the logout with a heading and a way back in", async () => {
    render(LogoutPage, { data: { message: "logout", signedIn: false } });
    await expect
      .element(page.getByRole("heading", { level: 1 }))
      .toHaveTextContent("logout_success");
    await expect.element(page.getByText("logout_description")).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: "login_again" }))
      .toHaveAttribute("href", "/login");
  });

  test("explains an expired session", async () => {
    render(LogoutPage, { data: { message: "expired", signedIn: false } });
    await expect
      .element(page.getByRole("heading", { level: 1 }))
      .toHaveTextContent("session_expired");
    await expect.element(page.getByText("session_expired_description")).toBeVisible();
  });

  test("a direct visit offers a deliberate logout instead of ending the session", async () => {
    render(LogoutPage, { data: { message: "logout", signedIn: true } });
    await expect.element(page.getByRole("heading", { level: 1 })).toHaveTextContent("logout");
    await expect
      .element(page.getByRole("button", { name: "logout", exact: true }))
      .toHaveAttribute("type", "submit");
    expect(document.querySelector("form")?.method).toBe("post");
    expect(document.querySelector("form")?.getAttribute("action")).toBe("/logout?/logout");
  });

  test.each([
    ["logout", "expired"],
    ["switchOrganisation", "logout"],
    ["clearCookies", "logout"]
  ] as const)(
    "a %s the server could not complete says so and retries it",
    async (action, message) => {
      render(LogoutPage, {
        data: { message: "logout", signedIn: true },
        form: { signOutFailed: action, message }
      });
      await expect
        .element(page.getByRole("heading", { level: 1 }))
        .toHaveTextContent("logout_unavailable");
      await expect.element(page.getByText("logout_unavailable_description")).toBeVisible();
      await expect
        .element(page.getByRole("button", { name: "retry" }))
        .toHaveAttribute("type", "submit");
      const form = document.querySelector("form");
      expect(form?.method).toBe("post");
      expect(form?.getAttribute("action")).toBe(`/logout?/${action}`);
      expect(form?.querySelector<HTMLInputElement>("input[name=message]")?.value).toBe(message);
    }
  );
});
