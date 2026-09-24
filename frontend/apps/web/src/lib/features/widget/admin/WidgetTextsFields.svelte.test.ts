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

describe("WidgetTextsFields and the save's echo", () => {
  // The page applies each change at once; the server answers later with the
  // texts whitespace-collapsed, the way the API stores them.
  function renderEditing() {
    const onChange = vi.fn<(change: Partial<WidgetTexts>) => void>();
    let current: WidgetTexts = { ...texts };
    const screen = render(WidgetTextsFields, {
      texts: current,
      onChange: (change) => {
        onChange(change);
        current = { ...current, ...change };
        void screen.rerender({ texts: current });
      }
    });
    const echo = (change: Partial<WidgetTexts>) => {
      current = { ...current, ...change };
      return screen.rerender({ texts: current });
    };
    return { onChange, echo };
  }

  test("a trimmed echo never eats the space or line break being typed", async () => {
    const { onChange, echo } = renderEditing();
    const welcome = page.getByLabelText("widget_admin_text_welcome", { exact: true });
    await userEvent.fill(welcome, "");
    await userEvent.type(welcome, "Välkommen till ");

    await echo({ welcome: "Välkommen till" });
    await expect.element(welcome).toHaveValue("Välkommen till ");
    await expect.element(welcome).toHaveFocus();

    await userEvent.type(welcome, "kommunen{Enter}");
    await echo({ welcome: "Välkommen till kommunen" });
    await expect.element(welcome).toHaveValue("Välkommen till kommunen\n");
    await userEvent.type(welcome, "Hej");
    expect(onChange).toHaveBeenLastCalledWith({ welcome: "Välkommen till kommunen\nHej" });

    // Once the field is left it shows what visitors will see.
    await echo({ welcome: "Välkommen till kommunen Hej" });
    await userEvent.tab();
    await expect.element(welcome).toHaveValue("Välkommen till kommunen Hej");
  });

  test("a value that really changed replaces the field, focused or not", async () => {
    const { echo } = renderEditing();
    const title = page.getByLabelText("widget_admin_text_title", { exact: true });
    await userEvent.click(title);
    await userEvent.type(title, " ");

    // Another editor, a template or a reload: adopted even mid-edit.
    await echo({ title: "Kontakta oss" });
    await expect.element(title).toHaveValue("Kontakta oss");
  });

  test("a refused text shows its reason at the field", async () => {
    render(WidgetTextsFields, {
      texts,
      onChange: vi.fn(),
      errors: { suggested_questions: "Frågorna godtogs inte", footer_text: "För lång" }
    });
    const footer = page.getByLabelText("widget_admin_text_footer", { exact: true });
    await expect.element(footer).toHaveAttribute("aria-invalid", "true");
    await expect.element(footer).toHaveAccessibleDescription(/För lång/);
    await expect.element(page.getByText("Frågorna godtogs inte")).toBeVisible();
  });

  test("a required subtitle is kept in the field, not sent, when it is emptied", async () => {
    const onChange = vi.fn();
    render(WidgetTextsFields, {
      texts,
      onChange,
      subtitleRequired: "Mallen låser upplysningen"
    });
    const subtitle = page.getByLabelText("widget_admin_text_subtitle", { exact: true });

    await userEvent.clear(subtitle);
    await userEvent.fill(subtitle, "   ");
    expect(onChange).not.toHaveBeenCalled();
    await expect.element(subtitle).toHaveValue("   ");
    await expect.element(subtitle).toHaveAttribute("aria-invalid", "true");
    await expect.element(subtitle).toHaveAccessibleDescription(/Mallen låser upplysningen/);

    await userEvent.fill(subtitle, "Du chattar med AI.");
    expect(onChange).toHaveBeenLastCalledWith({ subtitle: "Du chattar med AI." });
    await expect.element(subtitle).not.toHaveAccessibleDescription(/Mallen låser/);
  });

  test("a subtitle held back while required is sent once it no longer is", async () => {
    const onChange = vi.fn();
    const screen = render(WidgetTextsFields, {
      texts,
      onChange,
      subtitleRequired: "Widgeten är aktiv"
    });
    const subtitle = page.getByLabelText("widget_admin_text_subtitle", { exact: true });
    await userEvent.clear(subtitle);
    await expect.element(subtitle).toHaveAttribute("aria-invalid", "true");
    expect(onChange).not.toHaveBeenCalled();

    await screen.rerender({ subtitleRequired: undefined });
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledWith({ subtitle: "" }));
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
