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

import ChangePasswordDialog from "./ChangePasswordDialog.svelte";

const capability = {
  source: "eneo" as const,
  policy: {
    minLength: 15,
    maxBytes: 72,
    requiresUppercase: false,
    requiresLowercase: false,
    requiresNumber: false,
    requiresSymbol: false
  }
};

describe("change password dialog", () => {
  test("provides password-manager metadata and three correctly typed password fields", async () => {
    render(ChangePasswordDialog, { capability, username: "person@example.com" });

    await page.getByRole("button", { name: "change_password" }).click();

    const current = page.getByLabelText("current_password");
    const next = page.getByLabelText("new_password", { exact: true });
    const confirmation = page.getByLabelText("confirm_new_password");
    await expect.element(current).toBeVisible();
    await expect.element(next).toBeVisible();
    await expect.element(confirmation).toBeVisible();
    expect(current.element().getAttribute("autocomplete")).toBe("current-password");
    expect(next.element().getAttribute("autocomplete")).toBe("new-password");
    expect(confirmation.element().getAttribute("autocomplete")).toBe("new-password");
    expect(current.element().hasAttribute("required")).toBe(true);
    expect(next.element().hasAttribute("required")).toBe(true);
    expect(confirmation.element().hasAttribute("required")).toBe(true);

    const username = document.querySelector<HTMLInputElement>(
      'input[name="username"][autocomplete="username"]'
    );
    expect(username?.value).toBe("person@example.com");
    expect(username?.readOnly).toBe(true);
  });

  test("allows paste, toggles visibility and clears secrets when closed", async () => {
    render(ChangePasswordDialog, { capability, username: "person@example.com" });
    await page.getByRole("button", { name: "change_password" }).click();

    const current = page.getByLabelText("current_password");
    await current.fill("current secret");
    const paste = new Event("paste", { bubbles: true, cancelable: true });
    expect(current.element().dispatchEvent(paste)).toBe(true);

    await page.getByRole("button", { name: "show_password" }).first().click();
    expect(current.element().getAttribute("type")).toBe("text");

    await page.getByRole("button", { name: "cancel" }).click();
    await page.getByRole("button", { name: "change_password" }).click();
    expect(page.getByLabelText("current_password").element().getAttribute("type")).toBe("password");
    expect(page.getByLabelText("current_password").element().getAttribute("value") ?? "").toBe("");
  });
});
