// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import SelectBehaviourV2Harness from "./test-harnesses/SelectBehaviourV2Harness.svelte";

const selectedModel = {
  id: "model-haiku-45",
  name: "claude-haiku-4-5",
  nickname: "Claude Haiku 4.5",
  description: "Anthropic fast model",
  token_limit: 200000,
  provider_type: "anthropic",
  provider_id: "provider-anthropic",
  provider_name: "Anthropic"
};

afterEach(() => {
  cleanup();
});

describe("SelectBehaviourV2", () => {
  it("dispatches change when a named behaviour preset is selected", async () => {
    render(SelectBehaviourV2Harness, {
      kwArgs: { temperature: null, top_p: null },
      selectedModel
    });

    await fireEvent.click(screen.getByRole("combobox", { name: m.select_model_behaviour() }));
    await fireEvent.click(screen.getByText(m.deterministic()));

    expect(screen.getByTestId("change-count").textContent).toBe("1");
    expect(screen.getByTestId("serialized-kwargs").textContent).toContain('"temperature":0.25');
  });

  it("dispatches change when custom behaviour temperature is edited", async () => {
    render(SelectBehaviourV2Harness, {
      kwArgs: { temperature: null, top_p: null },
      selectedModel
    });

    await fireEvent.click(screen.getByRole("combobox", { name: m.select_model_behaviour() }));
    await fireEvent.click(screen.getByText(m.custom()));

    const input = screen.getByRole("spinbutton");
    await fireEvent.input(input, { target: { value: "1.37" } });

    expect(Number(screen.getByTestId("change-count").textContent)).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId("serialized-kwargs").textContent).toContain('"temperature":1.37');
    expect(screen.getByTestId("serialized-kwargs").textContent).toContain('"top_p":null');
  });
});
