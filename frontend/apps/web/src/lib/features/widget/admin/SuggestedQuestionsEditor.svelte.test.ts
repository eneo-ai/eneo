import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { afterEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

import SuggestedQuestionsEditor from "./SuggestedQuestionsEditor.svelte";

// Rows commit on blur. Leave the field while the component is still mounted:
// the next test's cleanup would otherwise blur it into an unmounted rerender.
afterEach(() => (document.activeElement as HTMLElement | null)?.blur());

describe("SuggestedQuestionsEditor", () => {
  test("typing a new question and editing an existing one keep focus and commit on blur", async () => {
    const onChange = vi.fn<(questions: string[]) => void>();
    // The parent echoes committed questions back as the prop, like the editor page.
    const screen = render(SuggestedQuestionsEditor, {
      questions: ["Öppettider?"],
      onChange: (questions) => {
        onChange(questions);
        void screen.rerender({ questions });
      }
    });

    await userEvent.click(page.getByRole("button", { name: "widget_admin_questions_add" }));
    const inputs = page.getByRole("textbox");
    const added = inputs.nth(1);
    await expect.element(added).toHaveFocus();

    await userEvent.type(added, "Ny fråga");
    await expect.element(added).toHaveValue("Ny fråga");
    await expect.element(added).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();

    await userEvent.tab();
    expect(onChange).toHaveBeenLastCalledWith(["Öppettider?", "Ny fråga"]);

    const first = inputs.nth(0);
    await userEvent.click(first);
    await userEvent.keyboard("{End}");
    await userEvent.type(first, " idag");
    await expect.element(first).toHaveValue("Öppettider? idag");
    await expect.element(first).toHaveFocus();

    await userEvent.tab();
    expect(onChange).toHaveBeenLastCalledWith(["Öppettider? idag", "Ny fråga"]);
    expect(document.querySelectorAll("input").length).toBe(2);
  });
});

describe("SuggestedQuestionsEditor limit", () => {
  test("Add and Enter both stop at the API's four questions", async () => {
    const onChange = vi.fn<(questions: string[]) => void>();
    const screen = render(SuggestedQuestionsEditor, {
      questions: ["Ett", "Två", "Tre"],
      onChange: (questions) => {
        onChange(questions);
        void screen.rerender({ questions });
      }
    });
    const add = page.getByRole("button", { name: "widget_admin_questions_add" });
    await userEvent.click(add);
    const fourth = page.getByRole("textbox").nth(3);
    await expect.element(fourth).toHaveFocus();
    await userEvent.type(fourth, "Fyra");
    await expect.element(add).toBeDisabled();

    // Enter on the last row commits but never opens a fifth row.
    await userEvent.keyboard("{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(["Ett", "Två", "Tre", "Fyra"]);
    expect(document.querySelectorAll("input").length).toBe(4);
    await expect.element(add).toBeDisabled();
  });
});

describe("SuggestedQuestionsEditor and the save's echo", () => {
  test("a fresh copy of the saved list never wipes the row being typed", async () => {
    const onChange = vi.fn<(questions: string[]) => void>();
    // Like the editor page: a commit updates the prop at once; the server's
    // answer arrives later as a new array with the same questions.
    const screen = render(SuggestedQuestionsEditor, {
      questions: [],
      onChange: (questions) => {
        onChange(questions);
        void screen.rerender({ questions });
      }
    });

    await userEvent.click(page.getByRole("button", { name: "widget_admin_questions_add" }));
    const first = page.getByRole("textbox").nth(0);
    await userEvent.type(first, "Hur ansöker jag?");
    // Enter commits the question and opens the next row.
    await userEvent.keyboard("{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(["Hur ansöker jag?"]);
    const second = page.getByRole("textbox").nth(1);
    await expect.element(second).toHaveFocus();
    await userEvent.type(second, "Var finns");

    await screen.rerender({ questions: ["Hur ansöker jag?"] });

    await expect.element(second).toHaveValue("Var finns");
    await expect.element(second).toHaveFocus();
    expect(document.querySelectorAll("input").length).toBe(2);
  });

  test("a list that really changed replaces the rows", async () => {
    const screen = render(SuggestedQuestionsEditor, { questions: ["Ett"], onChange: vi.fn() });
    await screen.rerender({ questions: ["Två", "Tre"] });
    await expect.element(page.getByRole("textbox").nth(0)).toHaveValue("Två");
    await expect.element(page.getByRole("textbox").nth(1)).toHaveValue("Tre");
  });

  test("a repeated question is flagged at the row and never sent", async () => {
    const onChange = vi.fn<(questions: string[]) => void>();
    render(SuggestedQuestionsEditor, { questions: ["Öppettider?"], onChange });

    await userEvent.click(page.getByRole("button", { name: "widget_admin_questions_add" }));
    const second = page.getByRole("textbox").nth(1);
    await userEvent.type(second, "Öppettider?  ");
    await userEvent.tab();

    await expect.element(second).toHaveAttribute("aria-invalid", "true");
    await expect.element(second).toHaveAccessibleDescription("widget_admin_questions_duplicate");
    expect(onChange).not.toHaveBeenCalled();

    await userEvent.type(second, "idag");
    await userEvent.tab();
    expect(onChange).toHaveBeenLastCalledWith(["Öppettider?", "Öppettider? idag"]);
    await expect.element(second).toHaveAttribute("aria-invalid", "false");
  });
});
