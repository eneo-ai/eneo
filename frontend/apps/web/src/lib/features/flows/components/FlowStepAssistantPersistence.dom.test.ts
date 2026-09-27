import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowStepAssistantPersistenceHarness from "./test-harnesses/FlowStepAssistantPersistenceHarness.svelte";

// bits-ui's select needs these, which jsdom does not implement.
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

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

const reasoningModels = [
  {
    id: "model-gpt-54",
    name: "gpt-5.4-nano",
    nickname: "GPT-5.4 nano",
    description: "Reasoning-capable model",
    token_limit: 128000,
    provider_type: "openai",
    provider_id: "provider-openai",
    provider_name: "OpenAI",
    reasoning: true,
    supported_model_kwargs: {
      reasoning_effort: {
        supported: true,
        control: "select",
        options: ["low", "medium", "high"]
      }
    }
  }
];

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn()
  });
});

describe("Flow step assistant persistence wiring", () => {
  it("saves the selected completion model when the model picker changes", async () => {
    render(FlowStepAssistantPersistenceHarness, { availableModels: models });

    await fireEvent.click(screen.getByRole("button", { name: "GPT-4o mini" }));
    await fireEvent.click(screen.getByText("Claude Haiku 4.5"));

    expect(screen.getByTestId("save-call-count").textContent).toBe("1");
    expect(screen.getByTestId("last-save").textContent).toContain('"completion_model"');
    expect(screen.getByTestId("last-save").textContent).toContain('"id":"model-haiku-45"');
  });

  it("saves updated completion model kwargs when the behaviour picker changes", async () => {
    render(FlowStepAssistantPersistenceHarness, { availableModels: models });

    // The behaviour picker is a bits-ui select: it opens on pointerdown and
    // picks an option on pointerup.
    await fireEvent.pointerDown(screen.getByRole("button", { name: m.select_model_behaviour() }), {
      pointerType: "mouse",
      button: 0
    });
    const option = await screen.findByRole("option", { name: m.deterministic() });
    await fireEvent.pointerUp(option, { pointerType: "mouse", button: 0 });
    await fireEvent.click(option);

    expect(screen.getByTestId("save-call-count").textContent).toBe("1");
    expect(screen.getByTestId("last-save").textContent).toContain('"completion_model_kwargs"');
    expect(screen.getByTestId("last-save").textContent).toContain('"temperature":0.25');
  });

  it("shows the active assistant's reasoning effort after switching steps", async () => {
    render(FlowStepAssistantPersistenceHarness, {
      availableModels: reasoningModels
    });

    // The widget is a bits-ui Select: the trigger is a button whose text is
    // the rendered option label, not a native <select> with a value.
    const reasoningTrigger = screen.getByLabelText(m.reasoning_effort());

    expect(reasoningTrigger.textContent).toContain(m.parameter_option_high());

    await fireEvent.click(screen.getByTestId("select-second-assistant"));
    expect(reasoningTrigger.textContent).toContain(m.parameter_option_low());

    await fireEvent.click(screen.getByTestId("select-first-assistant"));
    expect(reasoningTrigger.textContent).toContain(m.parameter_option_high());
  });
});
