import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowAIBuilderCanvas from "./FlowAIBuilderCanvas.svelte";
import type { FlowDraftSpecCore, StepSpec } from "./protocol";

function makeStep(ref: string): StepSpec {
  return {
    plan_step_ref: ref,
    name: `Steg ${ref}`,
    assistant_spec: { instructions: "Gör något." },
    input_source: "previous_step"
  };
}

function makeSpec(stepRefs: string[]): FlowDraftSpecCore {
  return {
    flow_name: "Transkribera ljud till PDF",
    steps: stepRefs.map(makeStep)
  };
}

afterEach(() => {
  cleanup();
});

describe("FlowAIBuilderCanvas", () => {
  it("renders the draft plan as a vertical step diagram", () => {
    render(FlowAIBuilderCanvas, { spec: makeSpec(["a", "b", "c"]) });

    const renderedSteps = screen.getAllByTestId("ai-builder-draft-step");

    expect(screen.getByTestId("ai-builder-draft-canvas")).toBeTruthy();
    expect(renderedSteps.map((step) => step.textContent?.replace(/\s+/g, " ").trim())).toEqual([
      "1 Steg a",
      "2 Steg b",
      "3 Steg c"
    ]);
    expect(renderedSteps.map((step) => step.dataset.stepRef)).toEqual(["a", "b", "c"]);
    expect(screen.getAllByTestId("ai-builder-draft-edge")).toHaveLength(2);
  });

  it("shows the assembling skeleton while streaming before steps arrive", () => {
    render(FlowAIBuilderCanvas, { spec: makeSpec([]), isStreaming: true });

    expect(screen.getByText(m.ai_builder_canvas_assembling())).toBeTruthy();
    expect(screen.queryByTestId("ai-builder-draft-canvas")).toBeNull();
  });

  it("shows the empty state when there are no steps and nothing is streaming", () => {
    render(FlowAIBuilderCanvas, { spec: makeSpec([]) });

    expect(screen.getByText(m.flow_graph_empty())).toBeTruthy();
    expect(screen.queryByTestId("ai-builder-draft-canvas")).toBeNull();
  });

  it("renders the diagram instead of the streaming skeleton once steps are available", () => {
    render(FlowAIBuilderCanvas, { spec: makeSpec(["a"]), isStreaming: true });

    expect(screen.getByTestId("ai-builder-draft-canvas")).toBeTruthy();
    expect(screen.queryByText(m.ai_builder_canvas_assembling())).toBeNull();
  });
});
