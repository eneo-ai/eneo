// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import SelectAIModelV2Harness from "./test-harnesses/SelectAIModelV2Harness.svelte";

const models = [
  {
    id: "model-4o-mini",
    name: "gpt-4o-mini",
    nickname: "GPT-4o mini",
    description: "Fast default model",
    token_limit: 128000,
    provider_type: "openai",
    provider_id: "provider-openai",
    provider_name: "OpenAI"
  },
  {
    id: "model-haiku-45",
    name: "claude-haiku-4-5",
    nickname: "Claude Haiku 4.5",
    description: "Anthropic fast model",
    token_limit: 200000,
    provider_type: "anthropic",
    provider_id: "provider-anthropic",
    provider_name: "Anthropic"
  }
];

afterEach(() => {
  cleanup();
});

describe("SelectAIModelV2", () => {
  it("dispatches change and updates the selected model when a new option is chosen", async () => {
    render(SelectAIModelV2Harness, {
      availableModels: models,
      selectedModel: models[0]
    });

    await fireEvent.click(screen.getByRole("combobox", { name: m.select_ai_model() }));
    await fireEvent.click(screen.getByText("Claude Haiku 4.5"));

    expect(screen.getByTestId("selected-model-id").textContent).toBe("model-haiku-45");
    expect(screen.getByTestId("change-count").textContent).toBe("1");
  });
});
