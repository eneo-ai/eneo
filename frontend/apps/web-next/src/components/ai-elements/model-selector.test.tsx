// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import { ModelDetails } from "./model-selector";

const messages = {
  model_info_for: "Model info for",
  model_context_label: "Context window",
  model_selector_context_value: "{tokens} tokens",
  model_selector_input_price: "Input price",
  model_selector_output_price: "Output price",
  model_selector_million_tokens: "1M tokens",
  model_cost_unknown: "Unknown",
  model_selector_no_description: "No description",
  model_detail_capabilities: "Capabilities",
  model_label_vision: "Vision",
  model_label_reasoning: "Reasoning",
  model_label_tool_calling: "Tools"
};

const model = {
  id: "m1",
  name: "gpt-4o",
  nickname: "GPT-4o",
  org: "OpenAI",
  provider_type: "openai",
  description: "A model",
  max_input_tokens: 128000,
  input_cost_per_token: 0.000005,
  output_cost_per_token: 0.000015,
  vision: false,
  reasoning: false,
  supports_tool_calling: false
} as unknown as Schema<"CompletionModelPublic">;

afterEach(cleanup);

function renderDetails(showPricing: boolean) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ModelDetails model={model} showPricing={showPricing} />
    </NextIntlClientProvider>
  );
}

it("shows input/output price rows when pricing is enabled", () => {
  renderDetails(true);
  expect(screen.queryByText("Input price")).not.toBeNull();
  expect(screen.queryByText("Output price")).not.toBeNull();
});

it("hides price rows entirely when pricing is disabled", () => {
  renderDetails(false);
  expect(screen.queryByText("Input price")).toBeNull();
  expect(screen.queryByText("Output price")).toBeNull();
  // The context window row stays visible regardless.
  expect(screen.queryByText("Context window")).not.toBeNull();
});
