import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import { tick } from "svelte";

import { m } from "$lib/paraglide/messages";
import { getFlowStepUxCopy } from "$lib/features/flows/flowStepUxCopy";
import FlowStepBehaviorSection from "./FlowStepBehaviorSection.svelte";
import type { LoadedAssistant } from "./FlowStepAssistantState.svelte";

// A model picker in the import graph reads matchMedia while its module loads.
vi.hoisted(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false
  })) as typeof window.matchMedia;
});

afterEach(cleanup);

const step = {
  id: "step-2",
  assistant_id: "assistant-2",
  step_order: 2,
  user_description: "Bedöm",
  input_source: "previous_step",
  input_type: "text",
  output_mode: "pass_through",
  output_type: "text"
} as FlowStep;

const stepUxCopy = getFlowStepUxCopy({ locale: "sv" });

function failedLoadProps(onRetryAssistantLoad: () => void) {
  return {
    step,
    isPublished: false,
    isAdvancedMode: false,
    isTranscribeOnly: false,
    assistant: null,
    assistantLoading: false,
    assistantLoadFailed: true,
    onRetryAssistantLoad,
    availableModels: [],
    steps: [step],
    formSchema: undefined,
    transcriptionEnabled: false,
    hasAudioInputSteps: false,
    stepUxCopy,
    instructionText: "",
    loadPromptVersions: async () => []
  };
}

// The real parent (FlowStepAssistantState.retryLoad) starts loading before the
// click handler returns; the stand-in does the same through rerender.
function renderFailedLoad() {
  let update: (props: Record<string, unknown>) => Promise<void> = async () => {};
  const retry = vi.fn(() => void update({ assistantLoadFailed: false, assistantLoading: true }));
  const { rerender } = render(FlowStepBehaviorSection, failedLoadProps(retry));
  update = rerender;
  return { retry, rerender };
}

describe("FlowStepBehaviorSection", () => {
  it("puts focus on the instruction once a retried read succeeds", async () => {
    const { retry, rerender } = renderFailedLoad();

    const retryButton = screen.getByRole("button", { name: m.retry() });
    retryButton.focus();
    await fireEvent.click(retryButton);
    expect(retry).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: m.retry() })).toBeNull();

    await rerender({
      assistantLoading: false,
      assistant: { id: "assistant-2" } as LoadedAssistant,
      instructionText: "Bedöm vad faktauppgifterna innebär."
    });

    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("textbox", { name: stepUxCopy.instructionsTitle })
      )
    );
  });

  it("puts focus on the read-only instruction of a published flow after a retry", async () => {
    const { rerender } = renderFailedLoad();
    await rerender({ isPublished: true });

    await fireEvent.click(screen.getByRole("button", { name: m.retry() }));
    await rerender({
      assistantLoading: false,
      assistant: { id: "assistant-2" } as LoadedAssistant,
      instructionText: "Bedöm vad faktauppgifterna innebär."
    });

    // The disabled textarea cannot take focus; the editor frame around it does.
    const instruction = screen.getByRole("textbox", { name: stepUxCopy.instructionsTitle });
    expect((instruction as HTMLTextAreaElement).disabled).toBe(true);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    expect(document.activeElement?.contains(instruction)).toBe(true);
  });

  it("leaves focus alone when the reader has moved to another step meanwhile", async () => {
    const { rerender } = renderFailedLoad();
    const stepList = document.body.appendChild(document.createElement("button"));

    await fireEvent.click(screen.getByRole("button", { name: m.retry() }));
    stepList.focus();
    await rerender({ step: { ...step, id: "step-3", assistant_id: "assistant-3", step_order: 3 } });
    await rerender({
      assistantLoading: false,
      assistant: { id: "assistant-3" } as LoadedAssistant,
      instructionText: "Skriv en sammanfattning."
    });

    // Focus would move one tick after the read settles.
    await tick();
    expect(document.activeElement).toBe(stepList);
    stepList.remove();
  });

  it("returns focus to Retry when the read fails again", async () => {
    const { rerender } = renderFailedLoad();

    await fireEvent.click(screen.getByRole("button", { name: m.retry() }));
    await rerender({ assistantLoading: false, assistantLoadFailed: true });

    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: m.retry() }))
    );
  });
});
