// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({
  GET: () =>
    Promise.resolve({
      data: {
        items: [
          {
            id: "entry-1",
            name: "Sammanfatta ett beslut",
            description: "Kort sammanfattning för tjänsteskrivelser",
            prompt: "Sammanfatta beslutet i tre meningar."
          }
        ]
      },
      response: new Response("{}")
    }),
  DELETE: vi.fn(),
  POST: vi.fn()
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

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PromptLibraryPage", () => {
  it("names the prompt table by the page title", async () => {
    const { container } = renderInApp(<PromptLibraryPage />);

    const table = await screen.findByRole("table", { name: "Promptbibliotek" });
    expect(within(table).getByText("Sammanfatta ett beslut")).toBeTruthy();
    // Each row's menu says whose it is.
    expect(
      within(table).getByRole("button", { name: "Fler åtgärder för Sammanfatta ett beslut" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);
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
    const menu = await screen.findByRole("button", {
      name: "Fler åtgärder för Sammanfatta ett beslut"
    });
    fireEvent.keyDown(menu, { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Ta bort" }));
    const confirm = await screen.findByRole("alertdialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Prompten är aktiv i styrningen för personlig assistent. Avaktivera den där först, och ta sedan bort den.",
        expect.anything()
      )
    );
  });

  it("shows each problem at its field on save, and moves focus to the first", async () => {
    renderInApp(<PromptLibraryPage />);
    await screen.findByRole("table", { name: "Promptbibliotek" });
    fireEvent.click(screen.getAllByRole("button", { name: "Ny prompt" })[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Ny prompt" });
    const save = within(dialog).getByRole("button", { name: "Spara" }) as HTMLButtonElement;
    // Never disabled: a disabled button says nothing about what is missing.
    expect(save.disabled).toBe(false);

    fireEvent.click(save);
    const name = within(dialog).getByLabelText("Namn");
    const prompt = within(dialog).getByLabelText("Prompt");
    for (const field of [name, prompt]) {
      expect(field.getAttribute("aria-invalid")).toBe("true");
    }
    expect(document.activeElement).toBe(name);
    await expectNoAxeViolations(dialog);

    fireEvent.change(name, { target: { value: "Sammanfatta ett protokoll" } });
    fireEvent.click(save);
    expect(name.getAttribute("aria-invalid")).toBeNull();
    expect(document.activeElement).toBe(prompt);
    expect(api.POST).not.toHaveBeenCalled();
  });
});
