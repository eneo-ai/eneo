// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
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
  roles: []
} as unknown as AdminUser;

async function renderEditor(
  user?: AdminUser,
  { policyResponse = ok(policy) }: { policyResponse?: Promise<unknown> } = {}
) {
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/users/password-policy/"
      ? policyResponse
      : ok({
          predefined_roles: { items: [{ id: "role-user", name: "Användare", permissions: [] }] },
          roles: { items: [] }
        })
  );
  renderInApp(<UserEditorDialog open onOpenChange={() => {}} user={user} />);
  const dialog = screen.getByRole("dialog", {
    name: user ? "Redigera användare" : "Skapa en ny användare"
  });
  await within(dialog).findByLabelText("Användare");
  return dialog;
}

const field = (dialog: HTMLElement, name: RegExp) =>
  within(dialog).getByLabelText(name) as HTMLInputElement;
const type = (dialog: HTMLElement, name: RegExp, value: string) =>
  fireEvent.change(field(dialog, name), { target: { value } });
const submit = (dialog: HTMLElement) =>
  fireEvent.submit(
    within(dialog)
      .getByRole("button", { name: /^(Skapa användare|Spara ändringar)$/ })
      .closest("form")!
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
  it("states the backend's password policy before the field", async () => {
    const dialog = await renderEditor();

    for (const input of [field(dialog, /^Lösenord/), field(dialog, /^Bekräfta lösenord/)]) {
      expect(input.getAttribute("type")).toBe("password");
      expect(input.getAttribute("autocomplete")).toBe("new-password");
      expect(input.getAttribute("aria-required")).toBe("true");
    }
    // The policy's rules, not a length of its own (WCAG 3.3.2), before the
    // fields and read with them.
    const checklist = within(dialog).getByText(
      "Det nya lösenordet måste uppfylla följande krav:"
    ).parentElement!;
    expect(
      within(checklist)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual([
      "Använd minst 12 tecken – Inte uppfyllt ännu",
      "Inkludera en siffra 0–9 – Inte uppfyllt ännu",
      "Lösenorden matchar – Inte uppfyllt ännu"
    ]);
    for (const input of [field(dialog, /^Lösenord/), field(dialog, /^Bekräfta lösenord/)]) {
      expect(input.getAttribute("aria-describedby")?.split(" ")).toContain(checklist.id);
    }
    expect(api.GET).toHaveBeenCalledWith("/api/v1/users/password-policy/");
    await expectNoAxeViolations(document.body);
  });

  it("shows each problem at its field on submit and moves focus to the first", async () => {
    const dialog = await renderEditor();
    const create = within(dialog).getByRole("button", { name: "Skapa användare" });
    // Never disabled: pressing it says what is missing.
    expect((create as HTMLButtonElement).disabled).toBe(false);

    submit(dialog);

    expect(errorOf(field(dialog, /^Användarnamn/))).toContain("Ange ett användarnamn.");
    expect(errorOf(field(dialog, /^E-post/))).toContain(
      "Ange en e-postadress, till exempel namn@kommun.se."
    );
    expect(errorOf(field(dialog, /^Lösenord/))).toContain("Ange ett nytt lösenord.");
    expect(document.activeElement).toBe(field(dialog, /^Användarnamn/));
    expect(api.POST).not.toHaveBeenCalled();
    expect(toast.warning).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);
  });

  it("checks a new user's password against the policy and its confirmation", async () => {
    const dialog = await renderEditor();
    type(dialog, /^Användarnamn/, "anna.lind");
    type(dialog, /^E-post/, "anna.lind@example.se");

    type(dialog, /^Lösenord/, "sommar-2026");
    type(dialog, /^Bekräfta lösenord/, "sommar-2026");
    submit(dialog);
    expect(errorOf(field(dialog, /^Lösenord/))).toContain("Använd minst 12 tecken");
    expect(document.activeElement).toBe(field(dialog, /^Lösenord/));

    type(dialog, /^Lösenord/, "sommarlovet-kommer");
    type(dialog, /^Bekräfta lösenord/, "sommarlovet-kommer");
    submit(dialog);
    expect(errorOf(field(dialog, /^Lösenord/))).toContain("Inkludera en siffra 0–9");

    type(dialog, /^Lösenord/, "sommarlovet-2026");
    type(dialog, /^Bekräfta lösenord/, "sommarlovet-2025");
    submit(dialog);
    expect(errorOf(field(dialog, /^Bekräfta lösenord/))).toContain(
      "Lösenorden matchar inte. Skriv samma lösenord i båda fälten."
    );
    expect(document.activeElement).toBe(field(dialog, /^Bekräfta lösenord/));
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("creates the user, keeping focus on the busy button", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.POST.mockReturnValue(new Promise((settle) => (resolve = settle)));
    const dialog = await renderEditor();
    type(dialog, /^Användarnamn/, "anna.lind");
    type(dialog, /^E-post/, "anna.lind@example.se");
    type(dialog, /^Lösenord/, "sommarlovet-2026");
    type(dialog, /^Bekräfta lösenord/, "sommarlovet-2026");
    const create = within(dialog).getByRole("button", { name: "Skapa användare" });
    create.focus();

    submit(dialog);

    await waitFor(() => expect(create.getAttribute("aria-busy")).toBe("true"));
    expect((create as HTMLButtonElement).disabled).toBe(false);
    expect(document.activeElement).toBe(create);
    expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/users/", {
      body: expect.objectContaining({ username: "anna.lind", password: "sommarlovet-2026" })
    });
    resolve({ data: {}, response: new Response("{}") });
  });

  it("says at the password field what the backend refuses about it", async () => {
    api.POST.mockImplementation(() =>
      Promise.resolve({
        error: {
          message: "Password does not meet the local password policy.",
          eneo_error_code: 9059
        },
        response: new Response(null, { status: 400 })
      })
    );
    const dialog = await renderEditor();
    type(dialog, /^Användarnamn/, "anna.lind");
    type(dialog, /^E-post/, "anna.lind@example.se");
    type(dialog, /^Lösenord/, "sommarlovet-2026");
    type(dialog, /^Bekräfta lösenord/, "sommarlovet-2026");

    submit(dialog);

    await waitFor(() =>
      expect(errorOf(field(dialog, /^Lösenord/))).toContain(
        "Det nya lösenordet uppfyller inte den aktuella lösenordspolicyn."
      )
    );
    expect(document.activeElement).toBe(field(dialog, /^Lösenord/));
    expect(toast.error).not.toHaveBeenCalled();
    // Changing the password clears it.
    type(dialog, /^Lösenord/, "sommarlovet-2027");
    expect(errorOf(field(dialog, /^Lösenord/))).toBeNull();
  });

  it("keeps an existing user's password unless a new one is typed twice", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    const dialog = await renderEditor(existing);
    const password = field(dialog, /^Lösenord/);

    expect(password.getAttribute("aria-required")).toBeNull();
    const hint = within(dialog).getByText(
      "Lämna båda fälten tomma för att behålla lösenordet. För att byta anger du ett nytt lösenord i båda fälten. Nuvarande lösenord behövs inte."
    );
    expect(password.getAttribute("aria-describedby")?.split(" ")).toContain(hint.id);

    // A new password needs its confirmation…
    type(dialog, /^Lösenord/, "vinterlovet-2026");
    expect(field(dialog, /^Bekräfta lösenord/).getAttribute("aria-required")).toBe("true");
    submit(dialog);
    expect(errorOf(field(dialog, /^Bekräfta lösenord/))).toContain(
      "Skriv det nya lösenordet en gång till."
    );
    await expectNoAxeViolations(document.body);

    // …and without one the rest saves.
    type(dialog, /^Lösenord/, "");
    submit(dialog);
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/users/{username}/", {
        params: { path: { username: "bo.ek" } },
        body: expect.objectContaining({ email: "bo.ek@example.se", password: undefined })
      })
    );
  });

  it("says so when the policy cannot be read, and saves no new account without it", async () => {
    const dialog = await renderEditor(undefined, {
      policyResponse: Promise.resolve({
        error: { message: "Boom" },
        response: new Response(null, { status: 500 })
      })
    });
    await within(dialog).findByText(
      "Lösenordspolicyn kunde inte hämtas. Ladda om sidan för att försöka igen."
    );
    expect(within(dialog).queryByLabelText(/^Lösenord/)).toBeNull();
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
