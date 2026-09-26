// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { UserEditorDialog } from "./user-editor";
import type { AdminUser } from "./users";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

async function renderEditor(user?: AdminUser) {
  api.GET.mockImplementation(() =>
    ok({
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

afterEach(() => vi.clearAllMocks());

describe("UserEditorDialog", () => {
  it("asks a new user's password twice, and says at the confirmation when they differ", async () => {
    const dialog = await renderEditor();
    fireEvent.change(field(dialog, /^Användarnamn/), { target: { value: "anna.lind" } });
    fireEvent.change(field(dialog, /^E-post/), { target: { value: "anna.lind@example.se" } });
    for (const input of [field(dialog, /^Lösenord/), field(dialog, /^Bekräfta lösenord/)]) {
      expect(input.getAttribute("type")).toBe("password");
      expect(input.getAttribute("autocomplete")).toBe("new-password");
      expect(input.getAttribute("aria-required")).toBe("true");
    }
    const hint = within(dialog).getByText("Behöver vara minst 7 tecken långt");
    expect(field(dialog, /^Lösenord/).getAttribute("aria-describedby")).toContain(hint.id);

    fireEvent.change(field(dialog, /^Lösenord/), { target: { value: "sommar-2026" } });
    field(dialog, /^Bekräfta lösenord/).focus();
    fireEvent.change(field(dialog, /^Bekräfta lösenord/), { target: { value: "sommar-2025" } });
    fireEvent.blur(field(dialog, /^Bekräfta lösenord/));

    const error = within(dialog).getByText("Lösenorden matchar inte");
    const confirmation = field(dialog, /^Bekräfta lösenord/);
    expect(confirmation.getAttribute("aria-invalid")).toBe("true");
    expect(confirmation.getAttribute("aria-describedby")).toContain(error.id);
    const create = within(dialog).getByRole("button", { name: "Skapa användare" });
    expect((create as HTMLButtonElement).disabled).toBe(true);
    await expectNoAxeViolations(document.body);

    api.POST.mockReturnValue(new Promise(() => {}));
    fireEvent.change(confirmation, { target: { value: "sommar-2026" } });
    expect((create as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(create);
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/users/", {
        body: expect.objectContaining({ username: "anna.lind", password: "sommar-2026" })
      })
    );
  });

  it("keeps an existing user's password unless a new one is typed twice", async () => {
    const dialog = await renderEditor({
      id: "user-2",
      username: "bo.ek",
      email: "bo.ek@example.se",
      roles: []
    } as unknown as AdminUser);
    const password = field(dialog, /^Lösenord/);
    const save = within(dialog).getByRole("button", { name: "Spara ändringar" });

    expect(password.getAttribute("aria-required")).toBeNull();
    expect(password.getAttribute("placeholder")).toBe("Lämna tomt för att behålla lösenordet");
    expect((save as HTMLButtonElement).disabled).toBe(false);

    // A new password needs its confirmation.
    fireEvent.change(password, { target: { value: "vinter-2026" } });
    expect(field(dialog, /^Bekräfta lösenord/).getAttribute("aria-required")).toBe("true");
    expect((save as HTMLButtonElement).disabled).toBe(true);
    await expectNoAxeViolations(document.body);
  });
});
