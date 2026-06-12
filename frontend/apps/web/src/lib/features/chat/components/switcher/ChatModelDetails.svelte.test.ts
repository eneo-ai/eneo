import type { CompletionModel } from "@intric/intric-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";
import ChatModelDetails from "./ChatModelDetails.svelte";

const model = {
  id: "model-1",
  name: "gpt-test",
  nickname: "GPT Test",
  org: "OpenAI",
  description: "Best for careful analysis.",
  max_input_tokens: 1_100_000,
  max_output_tokens: 16_000,
  input_cost_per_token: "0.0000025",
  output_cost_per_token: "0.00001",
  vision: true,
  reasoning: true,
  supports_tool_calling: true
} as CompletionModel;

describe("ChatModelDetails", () => {
  it("shows the admin guidance and model properties", async () => {
    render(ChatModelDetails, { model });

    await expect.element(page.getByRole("heading", { name: "GPT Test" })).toBeVisible();
    await expect.element(page.getByText("Best for careful analysis.")).toBeVisible();
    const formattedTokens = new Intl.NumberFormat(getLocale() === "sv" ? "sv-SE" : "en-US").format(
      model.max_input_tokens
    );
    await expect
      .element(page.getByText(m.model_selector_context_value({ tokens: formattedTokens })))
      .toBeVisible();
    await expect.element(page.getByText("$2.50")).toBeVisible();
    await expect.element(page.getByText("$10.00")).toBeVisible();
    await expect.element(page.getByText(m.model_label_vision())).toBeVisible();
    await expect.element(page.getByText(m.model_label_reasoning())).toBeVisible();
    await expect.element(page.getByText(m.model_label_tool_calling())).toBeVisible();
  });

  it("uses clear fallbacks when optional metadata is missing", async () => {
    render(ChatModelDetails, {
      model: {
        ...model,
        description: null,
        input_cost_per_token: null,
        output_cost_per_token: null
      }
    });

    await expect.element(page.getByText(m.model_selector_no_description())).toBeVisible();
    await expect
      .element(page.getByText(m.model_cost_unknown(), { exact: true }).first())
      .toBeVisible();
  });
});
