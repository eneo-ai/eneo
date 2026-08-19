import { describe, expect, it, vi } from "vitest";
import { writable } from "svelte/store";

import { FlowStepAssistantState, type LoadedAssistant } from "./FlowStepAssistantState.svelte.ts";
import type { FlowStep, Eneo } from "@eneo/eneo-js";
import type { FlowEditor } from "../FlowEditor";

function makeStep(assistantId: string): FlowStep {
  return {
    id: `step-${assistantId}`,
    assistant_id: assistantId,
    step_order: assistantId === "assistant-1" ? 1 : 2,
    user_description: `Step ${assistantId}`,
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text"
  };
}

function makeState(activeStep: { current: FlowStep | null }) {
  const flowEditor = {
    loadAssistant: vi.fn(async (assistantId: string) => ({ id: assistantId, name: assistantId })),
    saveAssistant: vi.fn(),
    updateAssistantImmediately: vi.fn(),
    flushAssistantSaves: vi.fn(async () => {})
  };
  const availability = vi.fn(async () => ({
    available: false,
    disabled_reason: "no_assignment" as const
  }));
  const state = new FlowStepAssistantState({
    flowEditor: flowEditor as unknown as FlowEditor,
    eneo: {
      files: { delete: vi.fn() },
      helpAssistants: { runs: { availability } }
    } as unknown as Eneo,
    attachmentRules: writable({}),
    newAttachments: writable([]),
    clearUploads: vi.fn(),
    getActiveStep: () => activeStep.current
  });
  return { state, flowEditor, availability };
}

describe("FlowStepAssistantState", () => {
  it("clears the previous assistant immediately when the active step changes", async () => {
    const activeStep = { current: makeStep("assistant-1") };
    const { state } = makeState(activeStep);

    await state.load("assistant-1");
    expect(state.assistant?.id).toBe("assistant-1");

    activeStep.current = makeStep("assistant-2");
    state.syncWithActiveStep(activeStep.current);

    expect(state.assistant).toBeNull();
    expect(state.loading).toBe(true);
  });

  it("does not save stale assistant edits to the newly active step", () => {
    const activeStep = { current: makeStep("assistant-2") };
    const { state, flowEditor } = makeState(activeStep);

    state.assistant = { id: "assistant-1", name: "assistant-1" } as unknown as LoadedAssistant;
    state.updateField("completion_model_kwargs", { reasoning_effort: "high" });

    expect(flowEditor.saveAssistant).not.toHaveBeenCalled();
    expect(flowEditor.updateAssistantImmediately).not.toHaveBeenCalled();
  });

  it("does not save model settings for a deterministic step", () => {
    const activeStep = {
      current: { ...makeStep("assistant-1"), output_mode: "render_verbatim" as const }
    };
    const { state, flowEditor } = makeState(activeStep);
    state.assistant = {
      id: "assistant-1",
      name: "Render PDF",
      completion_model: null,
      completion_model_kwargs: {}
    } as unknown as LoadedAssistant;

    state.updateField("completion_model_kwargs", { reasoning_effort: "high" });

    expect(flowEditor.saveAssistant).not.toHaveBeenCalled();
    expect(flowEditor.updateAssistantImmediately).not.toHaveBeenCalled();
  });

  it("loads Prompt Guide availability once per selected assistant", async () => {
    const activeStep = { current: makeStep("assistant-1") };
    const { state, availability } = makeState(activeStep);

    await state.load("assistant-1");
    await state.load("assistant-1");

    await vi.waitFor(() => expect(availability).toHaveBeenCalledTimes(1));
    expect(state.promptGuideAvailability).toEqual({
      available: false,
      disabled_reason: "no_assignment"
    });
  });

  it("reloads the same assistant when its external revision changes", async () => {
    const activeStep = { current: makeStep("assistant-1") };
    const { state, flowEditor } = makeState(activeStep);

    state.syncWithActiveStep(activeStep.current, 0);
    await vi.waitFor(() => expect(flowEditor.loadAssistant).toHaveBeenCalledTimes(1));

    state.syncWithActiveStep(activeStep.current, 1);

    await vi.waitFor(() => expect(flowEditor.loadAssistant).toHaveBeenCalledTimes(2));
  });
});
