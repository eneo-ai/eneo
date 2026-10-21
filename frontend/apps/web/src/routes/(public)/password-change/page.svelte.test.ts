import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import "../../../app.css";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$app/forms", () => ({
  enhance: () => ({ destroy: () => undefined })
}));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (args?: Record<string, unknown>) => string>>(
    {},
    {
      get: (_target, key) => (args?: Record<string, unknown>) =>
        args ? `${String(key)}:${Object.values(args).join(",")}` : String(key)
    }
  )
}));

import PasswordChangePage from "./+page.svelte";

const capability = {
  source: "eneo" as const,
  policy: {
    minLength: 12,
    maxBytes: 72,
    requiresUppercase: false,
    requiresLowercase: false,
    requiresNumber: false,
    requiresSymbol: false
  }
};

function renderPage(reason: "admin_set" | "expired") {
  render(PasswordChangePage, {
    data: { capability, reason, username: "person@example.com", next: null }
  });
}

describe("forced password change page", () => {
  test("asks for the one-time password the user just signed in with", async () => {
    renderPage("admin_set");
    await expect
      .element(page.getByText("password_change_required_admin_set", { exact: true }))
      .toBeVisible();
    await expect.element(page.getByText("password_change_required_current_hint")).toBeVisible();
  });

  test("asks for the expired password without assuming a fresh sign-in", async () => {
    renderPage("expired");
    await expect
      .element(page.getByText("password_change_required_expired", { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText("password_change_required_expired_current_hint"))
      .toBeVisible();
    await expect
      .element(page.getByText("password_change_required_current_hint", { exact: true }))
      .not.toBeInTheDocument();
  });
});
