import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

const updatePasswordLifecyclePolicy = vi.fn();
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ users: { updatePasswordLifecyclePolicy } })
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

import PasswordPolicyPanel from "./PasswordPolicyPanel.svelte";

describe("password policy panel", () => {
  beforeEach(() => {
    updatePasswordLifecyclePolicy.mockReset();
  });

  test("offers no switch for the one-time rule, which always applies", async () => {
    render(PasswordPolicyPanel, { policy: { max_age_days: null } });
    await expect.element(page.getByText("admin_password_policy_description")).toBeVisible();
    await expect.element(page.getByRole("switch")).not.toBeInTheDocument();
  });

  test("saves a valid age and reports the saved policy", async () => {
    updatePasswordLifecyclePolicy.mockResolvedValue({ max_age_days: 90 });
    render(PasswordPolicyPanel, { policy: { max_age_days: null } });

    const save = page.getByRole("button", { name: "save" });
    await expect.element(save).toBeDisabled();

    await page.getByLabelText("admin_password_policy_max_age").fill("90");
    await save.click();

    expect(updatePasswordLifecyclePolicy).toHaveBeenCalledWith({ max_age_days: 90 });
    await expect
      .element(page.getByRole("status"))
      .toHaveTextContent("admin_password_policy_updated");
    await expect.element(save).toBeDisabled();
  });

  test("an emptied age turns rotation off", async () => {
    updatePasswordLifecyclePolicy.mockResolvedValue({ max_age_days: null });
    render(PasswordPolicyPanel, { policy: { max_age_days: 30 } });

    await page.getByLabelText("admin_password_policy_max_age").fill("");
    await page.getByRole("button", { name: "save" }).click();

    expect(updatePasswordLifecyclePolicy).toHaveBeenCalledWith({ max_age_days: null });
  });

  test("a rejected save keeps the draft", async () => {
    updatePasswordLifecyclePolicy.mockRejectedValue(new Error("nope"));
    render(PasswordPolicyPanel, { policy: { max_age_days: null } });

    await page.getByLabelText("admin_password_policy_max_age").fill("45");
    await page.getByRole("button", { name: "save" }).click();

    await expect.element(page.getByRole("status")).toHaveTextContent("request_failed");
    await expect.element(page.getByLabelText("admin_password_policy_max_age")).toHaveValue("45");
  });

  test("rejects a malformed age before calling the backend and explains why", async () => {
    render(PasswordPolicyPanel, { policy: { max_age_days: 30 } });

    const maxAge = page.getByLabelText("admin_password_policy_max_age");
    await maxAge.fill("ninety");
    await page.getByRole("button", { name: "save" }).click();

    expect(updatePasswordLifecyclePolicy).not.toHaveBeenCalled();
    await expect.element(maxAge).toHaveAttribute("aria-invalid", "true");
    await expect.element(page.getByText("admin_password_policy_max_age_invalid")).toBeVisible();

    await maxAge.fill("");
    await userEvent.keyboard("{Tab}");
    await expect.element(maxAge).not.toHaveAttribute("aria-invalid");
  });
});
