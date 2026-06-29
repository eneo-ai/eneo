import type { CompletionModel } from "@intric/intric-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";

// The selector reads tenant.show_model_pricing from the app-wide Svelte context
// to gate the cost chip. That context is only set by the app shell, so stub it
// here with pricing enabled (the default).
vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    state: {
      tenant: {
        subscribe: (run: (tenant: { show_model_pricing: boolean }) => void) => {
          run({ show_model_pricing: true });
          return () => {};
        }
      }
    }
  })
}));

import SelectAIModelV2 from "./SelectAIModelV2.svelte";

const models = [
  {
    id: "gpt",
    name: "gpt-4o",
    nickname: "GPT-4o",
    org: "OpenAI",
    max_input_tokens: 128_000,
    vision: true
  },
  {
    id: "claude",
    name: "claude-3-5",
    nickname: "Claude 3.5",
    org: "Anthropic",
    max_input_tokens: 200_000,
    reasoning: true
  }
] as unknown as CompletionModel[];

describe("SelectAIModelV2", () => {
  it("surfaces the selection and lets the user pick another", async () => {
    render(SelectAIModelV2, { availableModels: models, selectedModel: models[0] });

    // Selected model is shown in the trigger and names it for assistive tech.
    const trigger = page.getByRole("button", { name: "GPT-4o" });
    await expect.element(trigger).toBeVisible();

    await trigger.click();

    // Both models are listed as options in the dropdown.
    await expect.element(page.getByRole("option", { name: "GPT-4o" })).toBeVisible();
    await expect.element(page.getByRole("option", { name: "Claude 3.5" })).toBeVisible();

    await page.getByRole("option", { name: "Claude 3.5" }).click();

    // Picking closes the popover and the trigger reflects the new model.
    await expect.element(page.getByRole("button", { name: "Claude 3.5" })).toBeVisible();
  });
});
