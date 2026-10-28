// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { brokenRule, readPasswordPolicy } from "@/features/auth/password-policy";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { UserEditorDialog } from "./user-editor";
import type { AdminUser } from "./users";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

/** The backend's local policy, as GET /api/v1/users/password-policy/ sends it. */
const policy = {
  min_length: 12,
  max_bytes: 72,
  requires_uppercase: false,
  requires_lowercase: false,
  requires_number: true,
  requires_symbol: false
};

const existing = {
  id: "user-2",
  username: "bo.ek",
  email: "bo.ek@example.se",
  roles: [],
  user_groups: [{ id: "g1", name: "Ekonomi" }]
} as unknown as AdminUser;

const groups = [
  { id: "g1", name: "Ekonomi", users: [] },
  { id: "g2", name: "Arkiv", users: [] }
];

async function renderEditor(
  user?: AdminUser,
  { policyResponse = ok(policy) }: { policyResponse?: Promise<unknown> } = {}
) {
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/users/password-policy/"
      ? policyResponse
      : path === "/api/v1/user-groups/"
        ? ok({ items: groups })
        : ok({
            predefined_roles: { items: [{ id: "role-user", name: "Användare", permissions: [] }] },
            roles: { items: [] }
          })
  );
  const { queryClient } = renderInApp(<Harness user={user} />);
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const dialog = screen.getByRole("dialog", {
    name: user ? "Redigera användare" : "Skapa en ny användare"
  });
  await within(dialog).findByLabelText("Användare");
  return { dialog, invalidate };
}

function Harness({ user }: { user?: AdminUser }) {
  const [open, setOpen] = useState(true);
  return <UserEditorDialog open={open} onOpenChange={setOpen} user={user} />;
}

/** The password a save sent, checked against the policy the backend sent. */
function sentPassword(call: number) {
  const password = (api.POST.mock.calls[call]?.[1] as { body: { password?: string } }).body
    .password;
  expect(password).toEqual(expect.any(String));
  expect(brokenRule(password!, readPasswordPolicy(policy)!)).toBeUndefined();
  return password!;
}

const field = (dialog: HTMLElement, name: RegExp) =>
  within(dialog).getByLabelText(name) as HTMLInputElement;
const type = (dialog: HTMLElement, name: RegExp, value: string) =>
  fireEvent.change(field(dialog, name), { target: { value } });
const replaceSwitch = (dialog: HTMLElement) =>
  within(dialog).getByRole("switch", { name: /^Generera ett nytt lösenord/ });
/** The submit button sits in the footer, outside the form it names. */
const submit = (dialog: HTMLElement) =>
  fireEvent.submit(
    (
      within(dialog).getByRole("button", {
        name: /^(Skapa användare|Spara ändringar)$/
      }) as HTMLButtonElement
    ).form!
  );
/** The field's error: the Astryx status message its aria-describedby names. */
const errorOf = (input: HTMLInputElement) =>
  input.getAttribute("aria-invalid") === "true"
    ? (input.getAttribute("aria-describedby") ?? "")
        .split(" ")
        .map((id) => document.getElementById(id))
        .filter((element) => element?.closest(".astryx-field-status"))
        .map((element) => element?.textContent ?? "")
        .join(" ")
    : null;

afterEach(() => vi.clearAllMocks());

describe("UserEditorDialog", () => {
  it("offers no field for typing a password and says one is generated", async () => {
    const { dialog } = await renderEditor();

    expect(dialog.querySelector('input[type="password"]')).toBeNull();
    within(dialog).getByText(
      "Eneo genererar ett lösenord som uppfyller lösenordspolicyn och visar det när kontot har skapats. Användaren måste välja ett eget lösenord vid nästa inloggning."
    );
    expect(api.GET).toHaveBeenCalledWith("/api/v1/users/password-policy/");
    await expectNoAxeViolations(document.body);
  });

  it("shows each problem at its field on submit and moves focus to the first", async () => {
    const { dialog } = await renderEditor();
    const create = within(dialog).getByRole("button", { name: "Skapa användare" });
    // Never disabled: pressing it says what is missing.
    expect((create as HTMLButtonElement).disabled).toBe(false);

    submit(dialog);

    expect(errorOf(field(dialog, /^Användarnamn/))).toContain("Ange ett användarnamn.");
    expect(errorOf(field(dialog, /^E-post/))).toContain(
      "Ange en e-postadress, till exempel namn@kommun.se."
    );
    expect(document.activeElement).toBe(field(dialog, /^Användarnamn/));
    expect(api.POST).not.toHaveBeenCalled();
    expect(toast.warning).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);
  });

  it("creates the user, keeping focus on the busy button", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.POST.mockReturnValue(new Promise((settle) => (resolve = settle)));
    const { dialog } = await renderEditor();
    type(dialog, /^Användarnamn/, "anna.lind");
    type(dialog, /^E-post/, "anna.lind@example.se");
    const create = within(dialog).getByRole("button", { name: "Skapa användare" });
    create.focus();

    submit(dialog);

    await waitFor(() => expect(create.getAttribute("aria-busy")).toBe("true"));
    expect((create as HTMLButtonElement).disabled).toBe(false);
    expect(document.activeElement).toBe(create);
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/users/", {
      body: expect.objectContaining({ username: "anna.lind", email: "anna.lind@example.se" })
    });
    sentPassword(0);
    resolve({ data: {}, response: new Response("{}") });
  });

  it("shows a new user's generated password once, then refreshes the list", async () => {
    api.POST.mockImplementation(() => ok({}));
    const { dialog, invalidate } = await renderEditor();
    type(dialog, /^Användarnamn/, "anna.lind");
    type(dialog, /^E-post/, "anna.lind@example.se");

    submit(dialog);

    const reveal = await screen.findByRole("dialog", { name: "Kontot har skapats" });
    const password = sentPassword(0);
    within(reveal).getByText(password);
    within(reveal).getByText(
      "Lämna lösenordet till anna.lind@example.se. Det visas inte igen. Användaren måste välja ett eget lösenord vid nästa inloggning."
    );
    expect(screen.queryByRole("dialog", { name: "Skapa en ny användare" })).toBeNull();
    // The list keeps its rows, and this dialog its row, while the password shows.
    expect(invalidate).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);

    fireEvent.click(within(reveal).getByRole("button", { name: "Klar" }));

    await waitFor(() => expect(screen.queryByText(password)).toBeNull());
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin-users"] });
  });

  it("toasts a refused save and keeps the form", async () => {
    api.POST.mockImplementation(() =>
      Promise.resolve({
        error: {
          message: "Password does not meet the local password policy.",
          eneo_error_code: 9059
        },
        response: new Response(null, { status: 400 })
      })
    );
    const { dialog } = await renderEditor();
    type(dialog, /^Användarnamn/, "anna.lind");
    type(dialog, /^E-post/, "anna.lind@example.se");

    submit(dialog);

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.queryByRole("dialog", { name: "Kontot har skapats" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Skapa en ny användare" })).toBe(dialog);
    expect(field(dialog, /^E-post/).value).toBe("anna.lind@example.se");
  });

  it("keeps an existing user's password unless a new one is generated", async () => {
    api.POST.mockImplementation(() => ok({}));
    const { dialog, invalidate } = await renderEditor(existing);
    const toggle = replaceSwitch(dialog);
    expect((toggle as HTMLInputElement).checked).toBe(false);
    // Always one-time: no tenant setting turns the hand-over into a lasting password.
    within(dialog).getByText(
      /^Det nuvarande lösenordet slutar fungera när du sparar\. .* Användaren måste välja ett eget lösenord vid nästa inloggning\.$/
    );
    await expectNoAxeViolations(document.body);

    submit(dialog);

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/users/{username}/", {
        params: { path: { username: "bo.ek" } },
        body: expect.objectContaining({ email: "bo.ek@example.se", password: undefined })
      })
    );
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin-users"] }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("replaces an existing user's password and shows the new one once", async () => {
    api.POST.mockImplementation(() => ok({}));
    const { dialog } = await renderEditor(existing);

    fireEvent.click(replaceSwitch(dialog));
    submit(dialog);

    const reveal = await screen.findByRole("dialog", { name: "Nytt lösenord har satts" });
    within(reveal).getByText(sentPassword(0));
    expect(api.POST.mock.calls[0]?.[0]).toBe("/api/v1/admin/users/{username}/");
  });

  it("refreshes the list when the one-time view is closed with its close button", async () => {
    api.POST.mockImplementation(() => ok({}));
    const { dialog, invalidate } = await renderEditor(existing);
    fireEvent.click(replaceSwitch(dialog));
    submit(dialog);
    const reveal = await screen.findByRole("dialog", { name: "Nytt lösenord har satts" });
    expect(invalidate).not.toHaveBeenCalled();

    fireEvent.click(within(reveal).getByRole("button", { name: "Stäng" }));

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin-users"] }));
  });

  it("says so, and sends nothing, when no password can meet the policy", async () => {
    const { dialog } = await renderEditor(existing, {
      policyResponse: ok({
        ...policy,
        min_length: 1,
        max_bytes: 3,
        requires_uppercase: true,
        requires_lowercase: true,
        requires_symbol: true
      })
    });
    fireEvent.click(replaceSwitch(dialog));

    submit(dialog);

    expect(toast.error).toHaveBeenCalledWith(
      "Lösenordspolicyn går inte att uppfylla, så inget lösenord kunde genereras. Kontakta den som driftar Eneo för er organisation."
    );
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("says so when the policy cannot be read, and generates no password without it", async () => {
    const { dialog } = await renderEditor(undefined, {
      policyResponse: Promise.resolve({
        error: { message: "Boom" },
        response: new Response(null, { status: 500 })
      })
    });
    await within(dialog).findByText(
      "Lösenordspolicyn kunde inte hämtas. Ladda om sidan för att försöka igen."
    );
    type(dialog, /^Användarnamn/, "anna.lind");
    type(dialog, /^E-post/, "anna.lind@example.se");

    submit(dialog);

    expect(document.activeElement).toBe(
      within(dialog).getByRole("button", { name: "Försök igen" })
    );
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);
  });
});

describe("UserEditorDialog username", () => {
  it("changes an existing user's username, sent only when it changed", async () => {
    api.POST.mockImplementation(() => ok({}));
    const { dialog } = await renderEditor(existing);
    const username = field(dialog, /^Användarnamn/);
    expect(username.disabled).toBe(false);
    within(dialog).getByText(/loggar ut och in igen/);

    submit(dialog);
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(
      (api.POST.mock.calls[0]?.[1] as { body: { username?: string } }).body.username
    ).toBeUndefined();
  });

  it("sends a new username under the current one", async () => {
    api.POST.mockImplementation(() => ok({}));
    const { dialog } = await renderEditor(existing);
    type(dialog, /^Användarnamn/, "bo.lind");

    submit(dialog);

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/users/{username}/", {
        params: { path: { username: "bo.ek" } },
        body: expect.objectContaining({ username: "bo.lind" })
      })
    );
  });

  it("does not let an existing username be emptied", async () => {
    const { dialog } = await renderEditor(existing);
    type(dialog, /^Användarnamn/, " ");

    submit(dialog);

    expect(errorOf(field(dialog, /^Användarnamn/))).toContain("Ange ett användarnamn.");
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("UserEditorDialog user groups", () => {
  // With a search field the trigger is a button that opens a listbox.
  const picker = (dialog: HTMLElement) =>
    within(dialog).getByRole("button", { name: /^Användargrupper/ });

  it("has no group field when creating a user", async () => {
    const { dialog } = await renderEditor();
    expect(within(dialog).queryByRole("button", { name: /^Användargrupper/ })).toBeNull();
  });

  it("assigns a group at once, apart from the save", async () => {
    api.POST.mockImplementation(() => ok({}));
    const { dialog, invalidate } = await renderEditor(existing);
    await within(dialog).findByRole("button", { name: "Tilldela" });
    within(dialog).getByText("Tilldelning och borttagning av grupper sparas direkt.");

    // Nothing picked: pressing says so at the picker.
    fireEvent.click(within(dialog).getByRole("button", { name: "Tilldela" }));
    expect(await within(dialog).findByText("Välj en användargrupp.")).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();

    fireEvent.click(picker(dialog));
    // Ekonomi is assigned already, so only Arkiv is offered.
    expect(screen.queryByRole("option", { name: "Ekonomi" })).toBeNull();
    fireEvent.click(await screen.findByRole("option", { name: "Arkiv" }));
    // The trigger's name carries the pick (Astryx names it by its label alone).
    expect(within(dialog).getByRole("button", { name: "Användargrupper: Arkiv" })).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Tilldela" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/user-groups/{id}/users/{user_id}/", {
        params: { path: { id: "g2", user_id: "user-2" } }
      })
    );
    expect(
      await within(dialog).findByRole("button", { name: "Ta bort från gruppen Arkiv" })
    ).toBeTruthy();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["user-groups"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin-users"] });
    // The dialog stays open: the save is a separate step.
    expect(screen.getByRole("dialog", { name: "Redigera användare" })).toBe(dialog);
    await expectNoAxeViolations(document.body);
  });

  it("removes a group at once", async () => {
    api.DELETE.mockImplementation(() => ok({}));
    const { dialog, invalidate } = await renderEditor(existing);

    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort från gruppen Ekonomi" }));

    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/user-groups/{id}/users/{user_id}/", {
        params: { path: { id: "g1", user_id: "user-2" } }
      })
    );
    await waitFor(() =>
      expect(
        within(dialog).queryByRole("button", { name: "Ta bort från gruppen Ekonomi" })
      ).toBeNull()
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin-users"] });
    expect(api.POST).not.toHaveBeenCalled();
  });
});
