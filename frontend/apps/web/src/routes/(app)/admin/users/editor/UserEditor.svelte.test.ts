import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { validateNewPassword } from "$lib/features/auth/passwordChange";
import UserEditor from "./UserEditor.svelte";
import "../../../../../app.css";

const user = {
  id: "user-1",
  username: "person",
  email: "person@example.com",
  roles: [],
  user_groups: []
};
const api = vi.hoisted(() => ({
  update: vi.fn<(request: unknown) => Promise<typeof user>>(),
  create: vi.fn<(request: unknown) => Promise<void>>(),
  invalidate: vi.fn<() => Promise<void>>(),
  toastError: vi.fn()
}));
vi.mock("$app/navigation", () => ({ invalidate: api.invalidate }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ users: api }) }));
vi.mock("$lib/core/errors", () => ({ toastError: api.toastError }));
const capability = vi.hoisted(() => ({
  source: "eneo" as const,
  policy: {
    minLength: 24,
    maxBytes: 72,
    requiresUppercase: true,
    requiresLowercase: true,
    requiresNumber: true,
    requiresSymbol: true
  }
}));
vi.mock("../ctx", () => ({
  getAdminUserCtx: () => ({
    roles: [],
    userGroups: [],
    passwordLifecyclePolicy: { require_change_after_admin_set: true, max_age_days: null },
    passwordCapability: capability
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

const emailInput = () => page.getByLabelText(m.email(), { exact: true });
const replaceSwitch = () => page.getByRole("switch", { name: m.admin_password_replace() });
const issuedPassword = () => page.getByLabelText(m.password(), { exact: true });
const saveButton = () => page.getByRole("button", { name: m.save_changes(), exact: true });
const doneButton = () => page.getByRole("button", { name: m.done(), exact: true });

function sentPassword(call: unknown): string {
  return (
    (call as { password?: string; update?: { password?: string } }).password ??
    (call as { update: { password: string } }).update.password
  );
}

describe("administrator user editor", () => {
  test("offers no field for typing a password", async () => {
    await openEditor();
    await expect.element(replaceSwitch()).toBeVisible();
    expect(document.querySelector('input[type="password"]')).toBeNull();
    await expect
      .element(page.getByLabelText(m.current_password(), { exact: true }))
      .not.toBeInTheDocument();
  });

  test("saves account edits without touching the password", async () => {
    await openEditor();
    await emailInput().fill("updated@example.com");
    await saveButton().click();
    await expect.poll(() => api.update.mock.calls.length).toBe(1);
    expect(api.update.mock.calls[0][0]).toEqual({
      user: { username: "person" },
      update: { email: "updated@example.com", roles: [] }
    });
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
    expect(api.invalidate).toHaveBeenCalledWith("admin:users");
  });

  test("replaces the password with one drawn against the policy and shows it once", async () => {
    await openEditor();
    await replaceSwitch().click();
    await saveButton().click();
    await expect.poll(() => api.update.mock.calls.length).toBe(1);
    const password = sentPassword(api.update.mock.calls[0][0]);
    expect(validateNewPassword(password, capability)).toBeUndefined();
    expect(api.update.mock.calls[0][0]).toEqual({
      user: { username: "person" },
      update: { password, roles: [] }
    });

    await expect.element(page.getByText(m.admin_password_replaced_title())).toBeVisible();
    await expect.element(issuedPassword()).toHaveValue(password);
    await expect.element(issuedPassword()).toHaveFocus();
    await expect.element(issuedPassword()).toHaveAttribute("readonly");
    // The list stays as it is while the password is on screen.
    expect(api.invalidate).not.toHaveBeenCalled();

    await doneButton().click();
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
    expect(api.invalidate).toHaveBeenCalledWith("admin:users");
    await page.getByRole("button", { name: m.edit(), exact: true }).click();
    await expect.element(replaceSwitch()).not.toBeChecked();
    await expect.element(page.getByText(password)).not.toBeInTheDocument();
  });

  test("keeps a shown password when clicking outside the dialog", async () => {
    await openEditor();
    await replaceSwitch().click();
    await saveButton().click();
    await expect.element(issuedPassword()).toBeVisible();
    await userEvent.click(document.body, { position: { x: 1, y: 1 } });
    await expect.element(issuedPassword()).toBeVisible();
  });

  test("clears discarded edits when reopened", async () => {
    await openEditor();
    await emailInput().fill("discarded@example.com");
    await replaceSwitch().click();
    await page.getByRole("button", { name: m.cancel(), exact: true }).click();
    await page.getByRole("button", { name: m.edit(), exact: true }).click();
    await expect.element(emailInput()).toHaveValue(user.email);
    await expect.element(replaceSwitch()).not.toBeChecked();
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

  test("creates a user with a generated password and shows it once", async () => {
    render(UserEditor, { mode: "create" });
    await page.getByRole("button", { name: m.create_user(), exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect.element(dialog.getByText(m.admin_password_generated_hint())).toBeVisible();
    await page.getByLabelText(m.username(), { exact: true }).fill("new-person");
    await emailInput().fill("new@example.com");
    await dialog.getByRole("button", { name: m.create_user(), exact: true }).click();
    await expect.poll(() => api.create.mock.calls.length).toBe(1);
    const password = sentPassword(api.create.mock.calls[0][0]);
    expect(validateNewPassword(password, capability)).toBeUndefined();
    expect(api.create).toHaveBeenCalledWith({
      username: "new-person",
      email: "new@example.com",
      password,
      roles: []
    });
    await expect.element(page.getByText(m.admin_user_created_title())).toBeVisible();
    await expect
      .element(page.getByText(m.admin_issued_password_handover({ email: "new@example.com" })))
      .toBeVisible();
    await expect.element(issuedPassword()).toHaveValue(password);
  });
});
