// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { ModelKwargsRows } from "./model-kwargs-rows";
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
