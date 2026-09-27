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

Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
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

    {
      const t = screen.getByRole("button", { name: m.select_model_behaviour() });
      await fireEvent.pointerDown(t, { pointerType: "mouse", button: 0 });
    }
    {
      const o = await screen.findByRole("option", { name: m.deterministic() });
      await fireEvent.pointerUp(o, { pointerType: "mouse", button: 0 });
      await fireEvent.click(o);
    }

    expect(screen.getByTestId("change-count").textContent).toBe("1");
    expect(screen.getByTestId("serialized-kwargs").textContent).toContain('"temperature":0.25');
  });

  it("dispatches change when custom behaviour temperature is edited", async () => {
    render(SelectBehaviourV2Harness, {
      kwArgs: { temperature: null, top_p: null },
      selectedModel
    });

    {
      const t = screen.getByRole("button", { name: m.select_model_behaviour() });
      await fireEvent.pointerDown(t, { pointerType: "mouse", button: 0 });
    }
    {
      const o = await screen.findByRole("option", { name: m.custom() });
      await fireEvent.pointerUp(o, { pointerType: "mouse", button: 0 });
      await fireEvent.click(o);
    }

    const input = screen.getByRole("spinbutton");
    await fireEvent.input(input, { target: { value: "1.37" } });

    expect(Number(screen.getByTestId("change-count").textContent)).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId("serialized-kwargs").textContent).toContain('"temperature":1.37');
    expect(screen.getByTestId("serialized-kwargs").textContent).toContain('"top_p":null');
  });
});
