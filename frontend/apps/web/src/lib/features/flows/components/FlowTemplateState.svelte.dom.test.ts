import { describe, expect, it, vi } from "vitest";
import { flushSync } from "svelte";
import { writable } from "svelte/store";
import type { Eneo, FlowStep } from "@eneo/eneo-js";
import type { FlowEditor } from "../FlowEditor";
import { FlowTemplateState } from "./FlowTemplateState.svelte.ts";

function step(id: string): FlowStep {
  return {
    id,
    assistant_id: `assistant-${id}`,
    step_order: 2,
    input_source: "previous_step",
    input_type: "text",
    output_type: "docx",
    output_mode: "template_fill",
    output_config: { bindings: { body: "" }, placeholders: ["body"] }
  };
}

// The editor panel receives configError and canRetry as props, so navigation
// has to reach them through reactivity, not only through a fresh getter read.
function observed(state: FlowTemplateState) {
  const seen = { configError: null as string | null, canRetry: false };
  const stop = $effect.root(() => {
    $effect(() => {
      seen.configError = state.configError;
      seen.canRetry = state.canRetry;
    });
  });
  flushSync();
  return { seen, stop };
}

describe("template failures seen through a reactive consumer", () => {
  it("follow the shown step in both navigation directions", async () => {
    let fail!: (reason: unknown) => void;
    const templates = {
      list: vi.fn(async () => []),
      upload: vi.fn(),
      inspect: vi.fn(
        () =>
          new Promise<never>((_, reject) => {
            fail = reject;
          })
      )
    };
    const state = new FlowTemplateState({
      eneo: { flows: { templates } } as unknown as Eneo,
      flowEditor: {
        state: { resource: writable({ id: "flow" }) },
        stepIdentity: (item: FlowStep) => item.id
      } as unknown as FlowEditor
    });
    const one = step("one");
    const two = step("two");
    const context = {
      activeStep: one,
      steps: [],
      formSchema: undefined,
      getStep: () => one,
      updateStep: vi.fn()
    };
    state.syncInspection(one, true, null);
    const { seen, stop } = observed(state);

    // The operation starts on step one and fails while step two is shown.
    const selecting = state.handleFileSelection("replacement", context);
    state.syncInspection(two, true, "asset-two");
    flushSync();
    fail(new Error("offline"));
    await selecting;
    flushSync();
    expect(seen.configError).toBeNull();
    expect(seen.canRetry).toBe(false);

    // Returning shows the failure and its retry without any other trigger.
    state.syncInspection(one, true, "configured");
    flushSync();
    expect(seen.configError).toBeTruthy();
    expect(seen.canRetry).toBe(true);

    // Leaving a shown failure must clear it from the other step's panel.
    state.syncInspection(two, true, "asset-two");
    flushSync();
    expect(seen.configError).toBeNull();
    expect(seen.canRetry).toBe(false);
    stop();
  });
});
