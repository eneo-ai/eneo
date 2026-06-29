import type { CompletionModel } from "@intric/intric-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";

// ChatModelDetails reads the tenant from the app-wide Svelte context to decide
// whether to show pricing. That context is only set by the app shell, so expose
// a small store here to keep this a pure render test.
const appContextMock = vi.hoisted(() => {
  type Tenant = { show_model_pricing: boolean };
  let current: Tenant = { show_model_pricing: true };
  const subscribers = new Set<(tenant: Tenant) => void>();

  return {
    tenant: {
      subscribe: (run: (tenant: Tenant) => void) => {
        subscribers.add(run);
        run(current);
        return () => {
          subscribers.delete(run);
        };
      }
    },
    setShowModelPricing: (show_model_pricing: boolean) => {
      current = { show_model_pricing };
      subscribers.forEach((run) => run(current));
    }
  };
});

vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    state: {
      tenant: appContextMock.tenant
    }
  })
}));

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
  beforeEach(() => {
    appContextMock.setShowModelPricing(true);
  });

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

  it("drops the price rows entirely when the model has no cost on record", async () => {
    render(ChatModelDetails, {
      model: {
        ...model,
        description: null,
        input_cost_per_token: null,
        output_cost_per_token: null
      }
    });

    await expect.element(page.getByText(m.model_selector_no_description())).toBeVisible();
    // No cost → omit the rows rather than showing a placeholder.
    await expect
      .element(page.getByText(m.model_selector_input_price(), { exact: true }))
      .not.toBeInTheDocument();
    await expect
      .element(page.getByText(m.model_selector_output_price(), { exact: true }))
      .not.toBeInTheDocument();
  });

  it("reacts when tenant pricing visibility changes", async () => {
    render(ChatModelDetails, { model });

    await expect
      .element(page.getByText(m.model_selector_input_price(), { exact: true }))
      .toBeVisible();

    appContextMock.setShowModelPricing(false);

    await expect
      .element(page.getByText(m.model_selector_input_price(), { exact: true }))
      .not.toBeInTheDocument();
  });
});
