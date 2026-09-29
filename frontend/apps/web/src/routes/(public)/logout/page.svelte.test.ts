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
    render(LogoutPage, { data: { message: "logout" } });
    await expect
      .element(page.getByRole("heading", { level: 1 }))
      .toHaveTextContent("logout_success");
    await expect.element(page.getByText("logout_description")).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: "login_again" }))
      .toHaveAttribute("href", "/login");
  });

  test("explains an expired session", async () => {
    render(LogoutPage, { data: { message: "expired" } });
    await expect
      .element(page.getByRole("heading", { level: 1 }))
      .toHaveTextContent("session_expired");
    await expect.element(page.getByText("session_expired_description")).toBeVisible();
  });
});
