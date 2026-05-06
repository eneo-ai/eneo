import { describe, expect, it, vi } from "vitest";
import { writable } from "svelte/store";

import {
  FlowStepAssistantState,
  type LoadedAssistant
} from "./FlowStepAssistantState.svelte.ts";
import type { FlowStep, Intric } from "@intric/intric-js";
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
    output_type: "text",
    mcp_policy: "inherit"
  };
}

function makeState(activeStep: { current: FlowStep | null }) {
  const flowEditor = {
    loadAssistant: vi.fn(async (assistantId: string) => ({ id: assistantId, name: assistantId })),
    saveAssistant: vi.fn(),
    updateAssistantImmediately: vi.fn(),
    flushAssistantSaves: vi.fn(async () => {})
  };
  const state = new FlowStepAssistantState({
    flowEditor: flowEditor as unknown as FlowEditor,
    intric: { files: { delete: vi.fn() } } as unknown as Intric,
    attachmentRules: writable({}),
    newAttachments: writable([]),
    clearUploads: vi.fn(),
    getActiveStep: () => activeStep.current
  });
  return { state, flowEditor };
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
});
