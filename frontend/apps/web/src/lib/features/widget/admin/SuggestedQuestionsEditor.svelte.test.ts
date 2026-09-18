import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

import SuggestedQuestionsEditor from "./SuggestedQuestionsEditor.svelte";

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
