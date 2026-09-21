import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { WidgetTexts } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

import WidgetTextsFields from "./WidgetTextsFields.svelte";
import { lockedTextFields } from "./templateLocks";

const texts: WidgetTexts = {
  title: "Fråga kommunen",
  welcome: "Hej!",
  placeholder: "",
  suggested_questions: [],
  subtitle: "Du chattar med en AI-assistent.",
  footer_text: "Personuppgifter",
  footer_link_url: null,
  footer_link_label: ""
};

describe("WidgetTextsFields locks", () => {
  test("template-governed fields are read-only and explain why; the rest stay editable", async () => {
    const onChange = vi.fn();
    render(WidgetTextsFields, {
      texts,
      onChange,
      lockedFields: lockedTextFields({ locked_groups: ["legal_texts"] }),
      lockHint: "Styrs av mallen Kommunblå"
    });

    const subtitle = page.getByLabelText("widget_admin_text_subtitle", { exact: true });
    const footer = page.getByLabelText("widget_admin_text_footer", { exact: true });
    const title = page.getByLabelText("widget_admin_text_title", { exact: true });
    await expect.element(subtitle).toBeDisabled();
    await expect.element(footer).toBeDisabled();
    await expect.element(subtitle).toHaveAccessibleDescription(/Styrs av mallen Kommunblå/);
    await expect.element(title).toBeEnabled();
    await expect.element(title).not.toHaveAccessibleDescription(/Styrs av mallen/);

    await userEvent.fill(title, "Ny titel");
    expect(onChange).toHaveBeenLastCalledWith({ title: "Ny titel" });
  });

  test("without a template nothing is locked", async () => {
    render(WidgetTextsFields, { texts, onChange: vi.fn() });
    await expect
      .element(page.getByLabelText("widget_admin_text_subtitle", { exact: true }))
      .toBeEnabled();
    expect(document.getElementById("widget-lock-hint")).toBeNull();
  });
});
