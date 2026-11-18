// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SettingsMarks } from "@/components/composites/settings-rows";
import { renderInApp } from "@/test/render";
import { ModelKwargsRows, modelSettingsMarkKey } from "./model-kwargs-rows";
import messages from "@/lib/i18n/messages/sv.json";
afterEach(cleanup);
it("keeps unsupported behaviour visible and explains supported parameter controls", () => {
  renderInApp(
    <ModelKwargsRows
      idPrefix="assistant"
      model={{
        supported_model_kwargs: { temperature: { supported: false }, top_p: { supported: true } }
      }}
      kwargs={{}}
      behaviourDescription="Behaviour"
      onChange={vi.fn()}
    />
  );
  expect(
    (screen.getByRole("combobox", { name: "Modellbeteende" }) as HTMLButtonElement).disabled
  ).toBe(true);
  expect(screen.getByText(messages.model_uses_specific_parameters_info)).toBeTruthy();
  expect(screen.getByText(messages.top_p_tooltip)).toBeTruthy();
});

it("is marked by row: the behaviour by its select's id, the model's own settings by their key", () => {
  const rows = (marked: string[]) => (
    <SettingsMarks marks={{ rows: new Set(marked), label: "Ändrad från chatten" }}>
      <ModelKwargsRows
        idPrefix="assistant"
        model={{
          supported_model_kwargs: { temperature: { supported: true }, top_p: { supported: true } }
        }}
        kwargs={{}}
        behaviourDescription="Behaviour"
        onChange={vi.fn()}
      />
    </SettingsMarks>
  );
  const settingsRow = () => screen.getByRole("group", { name: messages.model_settings });

  renderInApp(rows([modelSettingsMarkKey("assistant")]));
  expect(within(settingsRow()).queryByText("Ändrad från chatten")).toBeNull();
  expect(settingsRow().parentElement!.textContent).toContain("Ändrad från chatten");
  expect(screen.getAllByText("Ändrad från chatten")).toHaveLength(1);
  cleanup();

  renderInApp(rows(["assistant-model-behaviour"]));
  expect(screen.getAllByText("Ändrad från chatten")).toHaveLength(1);
  expect(
    screen.getByRole("combobox", { name: "Modellbeteende" }).closest("[class*='bg-ax-selected']")
  ).not.toBeNull();
  expect(modelSettingsMarkKey("app")).toBe("app-model-settings");
});
