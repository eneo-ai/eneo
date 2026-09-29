import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import UserEditor from "./UserEditor.svelte";
import "../../../../../app.css";

const user = {
  id: "user-1",
  username: "person",
  email: "person@example.com",
  roles: [],
  user_groups: []
};
const password = "a sufficiently long password";
const api = vi.hoisted(() => ({
  update: vi.fn<(request: unknown) => Promise<typeof user>>(),
  create: vi.fn<(request: unknown) => Promise<void>>(),
  invalidate: vi.fn<() => Promise<void>>(),
  toastError: vi.fn()
}));
vi.mock("$app/navigation", () => ({ invalidate: api.invalidate }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ users: api }) }));
vi.mock("$lib/core/errors", () => ({ toastError: api.toastError }));
vi.mock("../ctx", () => ({
  getAdminUserCtx: () => ({
    roles: [],
    userGroups: [],
    passwordCapability: {
      source: "eneo",
      policy: {
        minLength: 12,
        maxBytes: 72,
        requiresUppercase: false,
        requiresLowercase: false,
        requiresNumber: false,
        requiresSymbol: false
      }
    }
  })
}));

beforeEach(() => {
  vi.resetAllMocks();
  api.update.mockResolvedValue(user);
  api.create.mockResolvedValue();
  api.invalidate.mockResolvedValue();
});

async function openEditor() {
  render(UserEditor, { mode: "update", user: { ...user } });
  await page.getByRole("button", { name: m.edit(), exact: true }).click();
}

const nextInput = () => page.getByLabelText(m.new_password(), { exact: true });
const confirmationInput = () => page.getByLabelText(m.confirm_new_password(), { exact: true });
const emailInput = () => page.getByLabelText(m.email(), { exact: true });
const saveButton = () => page.getByRole("button", { name: m.save_changes(), exact: true });

describe("administrator user editor", () => {
  test("updates length and matching checks while typing without blurring", async () => {
    await openEditor();
    const minimum = page
      .getByRole("listitem")
      .filter({ hasText: m.password_policy_min_length({ min: 12 }) });
    const matching = page
      .getByRole("listitem")
      .filter({ hasText: m.password_policy_confirmation_matches() });
    await nextInput().click();
    await userEvent.keyboard("abcdefghijk");
    await expect.element(minimum).toHaveTextContent(m.password_policy_pending());
    await userEvent.keyboard("l");
    await expect.element(nextInput()).toHaveFocus();
    await expect.element(minimum).toHaveTextContent(m.password_policy_fulfilled());
    await userEvent.keyboard("{Backspace}");
    await expect.element(minimum).toHaveTextContent(m.password_policy_pending());
    await userEvent.keyboard("l");
    await confirmationInput().click();
    await userEvent.keyboard("abcdefghijkl");
    await expect.element(confirmationInput()).toHaveFocus();
    await expect.element(matching).toHaveTextContent(m.password_policy_fulfilled());
    await userEvent.keyboard("{Backspace}");
    await expect.element(matching).toHaveTextContent(m.password_policy_pending());
  });

  test("saves account edits with empty password fields and no current-password field", async () => {
    await openEditor();
    await expect.element(nextInput()).toBeVisible();
    await expect.element(confirmationInput()).toBeVisible();
    await expect
      .element(page.getByLabelText(m.current_password(), { exact: true }))
      .not.toBeInTheDocument();
    expect(nextInput().element().getAttribute("autocomplete")).toBe("new-password");
    expect(confirmationInput().element().getAttribute("autocomplete")).toBe("new-password");
    await emailInput().fill("updated@example.com");
    await saveButton().click();
    await expect.poll(() => api.update.mock.calls.length).toBe(1);
    expect(api.update.mock.calls[0][0]).toEqual({
      user: { username: "person" },
      update: { email: "updated@example.com", roles: [] }
    });
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
  });

  test("rejects mismatches, then submits only the matching new password", async () => {
    await openEditor();
    await nextInput().fill(password);
    await confirmationInput().fill(`${password}!`);
    await saveButton().click();
    await expect.element(page.getByText(m.passwords_dont_match(), { exact: true })).toBeVisible();
    await expect.element(confirmationInput()).toHaveFocus();
    expect(api.update).not.toHaveBeenCalled();
    await confirmationInput().fill(password);
    await saveButton().click();
    await expect.poll(() => api.update.mock.calls.length).toBe(1);
    expect(api.update.mock.calls[0][0]).toEqual({
      user: { username: "person" },
      update: { password, roles: [] }
    });
  });

  test("clears passwords and discarded account edits when reopened", async () => {
    await openEditor();
    await emailInput().fill("discarded@example.com");
    await nextInput().fill(password);
    await confirmationInput().fill(password);
    await page.getByRole("button", { name: m.cancel(), exact: true }).click();
    await page.getByRole("button", { name: m.edit(), exact: true }).click();
    await expect.element(nextInput()).toHaveValue("");
    await expect.element(confirmationInput()).toHaveValue("");
    await expect.element(emailInput()).toHaveValue(user.email);
    expect(api.update).not.toHaveBeenCalled();
  });

  test("preserves edits when saving fails so retry sends the same changes", async () => {
    api.update.mockRejectedValueOnce(new Error("Save failed"));
    await openEditor();
    await emailInput().fill("retry@example.com");
    await saveButton().click();
    await expect.poll(() => api.toastError.mock.calls.length).toBe(1);
    await expect.element(emailInput()).toHaveValue("retry@example.com");
    await saveButton().click();
    await expect.poll(() => api.update.mock.calls.length).toBe(2);
    expect(api.update.mock.calls[1][0]).toEqual(api.update.mock.calls[0][0]);
  });

  test("requires confirmation when creating a user", async () => {
    render(UserEditor, { mode: "create" });
    await page.getByRole("button", { name: m.create_user(), exact: true }).click();
    const dialog = page.getByRole("dialog");
    await page.getByLabelText(m.username(), { exact: true }).fill("new-person");
    await emailInput().fill("new@example.com");
    await nextInput().fill(password);
    await dialog.getByRole("button", { name: m.create_user(), exact: true }).click();
    await expect
      .element(page.getByText(m.password_field_required(), { exact: true }))
      .toBeVisible();
    expect(api.create).not.toHaveBeenCalled();
    await confirmationInput().fill(password);
    await dialog.getByRole("button", { name: m.create_user(), exact: true }).click();
    await expect.poll(() => api.create.mock.calls.length).toBe(1);
    expect(api.create).toHaveBeenCalledWith({
      username: "new-person",
      email: "new@example.com",
      password,
      roles: []
    });
  });
});
