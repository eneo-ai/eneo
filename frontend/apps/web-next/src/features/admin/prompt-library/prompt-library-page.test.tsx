// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const entries = [
  {
    id: "entry-1",
    name: "Sammanfatta ett beslut",
    description: "Kort sammanfattning för tjänsteskrivelser",
    current_version: 2,
    created_by_user_id: "user-1",
    created_at: "2026-09-01T08:00:00Z",
    updated_at: "2026-09-20T08:00:00Z"
  },
  {
    id: "entry-2",
    name: "Översätt ett protokoll",
    description: null,
    current_version: 1,
    created_by_user_id: "user-2",
    created_at: "2026-09-10T08:00:00Z",
    updated_at: "2026-09-25T08:00:00Z"
  }
];

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const api = vi.hoisted(() => ({
  GET: vi.fn(),
  DELETE: vi.fn(),
  POST: vi.fn(),
  PUT: vi.fn()
}));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { PromptLibraryPage } from "./prompt-library-page";

beforeEach(() => {
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/admin/prompt-library/"
      ? ok({ items: entries })
      : path === "/api/v1/admin/prompt-library/{id}/"
        ? ok({ ...entries[0], text: "Sammanfatta beslutet i tre meningar." })
        : ok({ items: [], count: 0 })
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/** Opens a row's menu from the keyboard and returns the menu element. */
function openRowMenu(name: string) {
  const trigger = screen.getByRole("button", { name: `Fler åtgärder för ${name}` });
  trigger.focus();
  // jsdom does not turn Enter into a click; Astryx opens menus on the key.
  fireEvent.keyDown(trigger, { key: "Enter" });
  return document.getElementById(trigger.getAttribute("aria-controls")!)!;
}

describe("PromptLibraryPage", () => {
  it("names the prompt table by the page title, newest change first", async () => {
    const { container } = renderInApp(<PromptLibraryPage />);

    const table = await screen.findByRole("table", { name: "Promptbibliotek" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell")[0]!.textContent)).toEqual([
      "Översätt ett protokoll",
      "Sammanfatta ett beslut"
    ]);
    // Each row's menu says whose it is.
    expect(
      within(table).getByRole("button", { name: "Fler åtgärder för Sammanfatta ett beslut" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("sorts by name from the column header", async () => {
    renderInApp(<PromptLibraryPage />);
    const table = await screen.findByRole("table", { name: "Promptbibliotek" });

    fireEvent.click(within(table).getByRole("button", { name: /Namn/ }));

    await waitFor(() => {
      const rows = within(table).getAllByRole("row").slice(1);
      expect(rows.map((row) => within(row).getAllByRole("cell")[0]!.textContent)).toEqual([
        "Sammanfatta ett beslut",
        "Översätt ett protokoll"
      ]);
    });
    expect(
      within(table).getByRole("columnheader", { name: /Namn/ }).getAttribute("aria-sort")
    ).toBe("ascending");
  });

  it("filters the list as you type, and clears back to the search field", async () => {
    renderInApp(<PromptLibraryPage />);
    await screen.findByRole("table", { name: "Promptbibliotek" });
    const search = screen.getByRole("textbox", { name: "Sök prompter" });

    fireEvent.change(search, { target: { value: "protokoll" } });
    const table = screen.getByRole("table", { name: "Promptbibliotek" });
    expect(within(table).queryByText("Sammanfatta ett beslut")).toBeNull();
    expect(within(table).getByText("Översätt ett protokoll")).toBeTruthy();

    fireEvent.change(search, { target: { value: "finns inte" } });
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText("Inga prompter matchar din sökning.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Rensa" }));

    expect((search as HTMLInputElement).value).toBe("");
    expect(document.activeElement).toBe(search);
    expect(await screen.findByRole("table", { name: "Promptbibliotek" })).toBeTruthy();
  });

  it("says why a prompt the personal assistant's governance uses cannot be deleted", async () => {
    // Its own code (9069), not the taken-name one it used to borrow.
    api.DELETE.mockImplementation(() =>
      Promise.resolve({
        error: {
          message:
            "Prompt 'Sammanfatta ett beslut' is referenced by the personal assistant governance policy.",
          eneo_error_code: 9069
        },
        response: new Response(null, { status: 409 })
      })
    );
    renderInApp(<PromptLibraryPage />);
    await screen.findByRole("table", { name: "Promptbibliotek" });
    fireEvent.click(
      within(openRowMenu("Sammanfatta ett beslut")).getByRole("menuitem", { name: "Ta bort" })
    );
    const confirm = await screen.findByRole("alertdialog", { name: "Ta bort prompt?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Prompten är aktiv i styrningen för personlig assistent. Avaktivera den där först, och ta sedan bort den.",
        expect.anything()
      )
    );
    expect(api.DELETE).toHaveBeenCalledWith("/api/v1/admin/prompt-library/{id}/", {
      params: { path: { id: "entry-1" } }
    });
  });

  it("deletes a prompt and announces it", async () => {
    api.DELETE.mockImplementation(() => ok({}));
    renderInApp(<PromptLibraryPage />);
    await screen.findByRole("table", { name: "Promptbibliotek" });
    fireEvent.click(
      within(openRowMenu("Översätt ett protokoll")).getByRole("menuitem", { name: "Ta bort" })
    );
    const confirm = await screen.findByRole("alertdialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("”Översätt ett protokoll” togs bort.")
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("shows each problem at its field on save, and moves focus to the first", async () => {
    renderInApp(<PromptLibraryPage />);
    await screen.findByRole("table", { name: "Promptbibliotek" });
    fireEvent.click(screen.getByRole("button", { name: "Ny prompt" }));
    const dialog = await screen.findByRole("dialog", { name: "Ny prompt" });
    const save = within(dialog).getByRole("button", { name: "Spara" }) as HTMLButtonElement;
    // Never disabled: a disabled button says nothing about what is missing.
    expect(save.disabled).toBe(false);

    fireEvent.click(save);
    const name = within(dialog).getByLabelText(/^Namn/);
    const prompt = within(dialog).getByLabelText(/^Prompt-text/);
    for (const field of [name, prompt]) {
      expect(field.getAttribute("aria-invalid")).toBe("true");
    }
    expect(document.activeElement).toBe(name);
    expect(within(dialog).getAllByText("Detta fält är obligatoriskt")).toHaveLength(2);
    await expectNoAxeViolations(dialog);

    fireEvent.change(name, { target: { value: "Sammanfatta ett protokoll" } });
    fireEvent.click(save);
    expect(name.getAttribute("aria-invalid")).toBeNull();
    expect(document.activeElement).toBe(prompt);
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("creates a prompt, announces it and closes the dialog", async () => {
    api.POST.mockImplementation(() =>
      ok({ ...entries[0], id: "entry-3", name: "Svara på remiss", current_version: 1 })
    );
    renderInApp(<PromptLibraryPage />);
    await screen.findByRole("table", { name: "Promptbibliotek" });
    fireEvent.click(screen.getByRole("button", { name: "Ny prompt" }));
    const dialog = await screen.findByRole("dialog", { name: "Ny prompt" });
    fireEvent.change(within(dialog).getByLabelText(/^Namn/), {
      target: { value: " Svara på remiss " }
    });
    fireEvent.change(within(dialog).getByLabelText(/^Prompt-text/), {
      target: { value: "Skriv ett remissvar." }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/prompt-library/", {
        body: { name: "Svara på remiss", description: null, text: "Skriv ett remissvar." }
      })
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("”Svara på remiss” skapades."));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Ny prompt" })).toBeNull());
  });

  it("edits the full prompt, and hands over to its version history", async () => {
    renderInApp(<PromptLibraryPage />);
    await screen.findByRole("table", { name: "Promptbibliotek" });
    fireEvent.click(
      within(openRowMenu("Sammanfatta ett beslut")).getByRole("menuitem", { name: "Redigera" })
    );
    const dialog = await screen.findByRole("dialog", { name: "Redigera prompt" });
    // The list is sparse: the text comes from the entry itself.
    const prompt = (await within(dialog).findByLabelText(/^Prompt-text/)) as HTMLTextAreaElement;
    expect(prompt.value).toBe("Sammanfatta beslutet i tre meningar.");
    expect(api.GET).toHaveBeenCalledWith("/api/v1/admin/prompt-library/{id}/", {
      params: { path: { id: "entry-1" } }
    });
    await expectNoAxeViolations(dialog);

    fireEvent.click(within(dialog).getByRole("button", { name: "Visa versionshistorik" }));

    expect(
      await screen.findByRole("dialog", { name: "Versionshistorik för Sammanfatta ett beslut" })
    ).toBeTruthy();
    expect(screen.queryByRole("dialog", { name: "Redigera prompt" })).toBeNull();
  });

  it("opens the version history from the row menu", async () => {
    renderInApp(<PromptLibraryPage />);
    await screen.findByRole("table", { name: "Promptbibliotek" });
    fireEvent.click(
      within(openRowMenu("Översätt ett protokoll")).getByRole("menuitem", {
        name: "Visa versionshistorik"
      })
    );
    expect(
      await screen.findByRole("dialog", { name: "Versionshistorik för Översätt ett protokoll" })
    ).toBeTruthy();
    expect(api.GET).toHaveBeenCalledWith("/api/v1/admin/prompt-library/{id}/versions/", {
      params: { path: { id: "entry-2" } }
    });
  });
});
