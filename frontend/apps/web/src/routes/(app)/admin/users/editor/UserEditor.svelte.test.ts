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
  toastError: vi.fn(),
  toast: { warning: vi.fn(), error: vi.fn() }
}));
vi.mock("$app/navigation", () => ({ invalidate: api.invalidate }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ users: api }) }));
vi.mock("$lib/core/errors", () => ({ toastError: api.toastError }));
vi.mock("$lib/components/toast", () => ({ toast: api.toast }));
const capability = vi.hoisted(() => ({
  source: "eneo" as const,
  policy: {
    minLength: 24,
    maxBytes: 72 as number | null,
    requiresUppercase: true,
    requiresLowercase: true,
    requiresNumber: true,
    requiresSymbol: true
  }
}));
/** Each test starts from this; one narrows the policy until nothing meets it. */
const strictPolicy = { ...capability.policy };
vi.mock("../ctx", () => ({
  getAdminUserCtx: () => ({
    roles: [],
    userGroups: [],
    passwordCapability: capability
  })
}));

beforeEach(() => {
  vi.resetAllMocks();
  Object.assign(capability.policy, strictPolicy);
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

/** The texts an element's aria-describedby points at, in order. */
function descriptions(element: Element): (string | undefined)[] {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim());
}

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

  test("names the one-time view and its hand-over for screen readers", async () => {
    await openEditor();
    await replaceSwitch().click();
    await saveButton().click();
    await expect.element(issuedPassword()).toHaveFocus();
    const handover = expect.stringContaining(
      m.admin_issued_password_handover({ email: user.email })
    );
    expect(descriptions(issuedPassword().element())).toEqual([
      m.admin_password_replaced_title(),
      handover
    ]);
    expect(descriptions(page.getByRole("dialog").element())).toEqual([handover]);
  });

  test("refreshes the list when the one-time view is closed with Escape", async () => {
    await openEditor();
    await replaceSwitch().click();
    await saveButton().click();
    await expect.element(issuedPassword()).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
    await expect.poll(() => api.invalidate.mock.calls).toEqual([["admin:users"]]);
  });

  test("shows no password when the save is refused, and a retry draws a fresh one", async () => {
    api.update.mockRejectedValueOnce(new Error("Save failed"));
    await openEditor();
    await replaceSwitch().click();
    await saveButton().click();
    await expect.poll(() => api.toastError.mock.calls.length).toBe(1);
    await expect.element(issuedPassword()).not.toBeInTheDocument();
    await expect.element(replaceSwitch()).toBeChecked();

    await saveButton().click();
    await expect.poll(() => api.update.mock.calls.length).toBe(2);
    const refused = sentPassword(api.update.mock.calls[0][0]);
    const accepted = sentPassword(api.update.mock.calls[1][0]);
    expect(accepted).not.toBe(refused);
    await expect.element(issuedPassword()).toHaveValue(accepted);
  });

  test("says so, and sends nothing, when no password can meet the policy", async () => {
    Object.assign(capability.policy, { minLength: 1, maxBytes: 3 });
    await openEditor();
    await replaceSwitch().click();
    await saveButton().click();
    await expect.poll(() => api.toast.error.mock.calls.length).toBe(1);
    expect(api.toast.error).toHaveBeenCalledWith(m.admin_password_policy_unsatisfiable());
    expect(api.update).not.toHaveBeenCalled();
    await expect.element(replaceSwitch()).toBeChecked();
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
    // Always one-time: no tenant setting can turn the hand-over into a lasting password.
    await expect
      .element(dialog.getByText(m.admin_password_generated_hint(), { exact: false }))
      .toHaveTextContent(m.admin_password_one_time_hint());
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
