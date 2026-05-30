// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

// The xyflow graph is replaced with a light stub so the canvas state machine and
// the draft adapter can be asserted in jsdom without a real graph render.
vi.mock("$lib/features/flows/components/FlowGraph.svelte", async () => ({
  default: (await import("./test-harnesses/FlowGraphStub.svelte")).default
}));

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
  it("renders the draft plan as a vertical, draft-isolated graph", () => {
    render(FlowAIBuilderCanvas, { spec: makeSpec(["a", "b", "c"]) });

    const graph = screen.getByTestId("flow-graph");
    expect(graph.getAttribute("data-steps")).toBe("3");
    expect(graph.getAttribute("data-direction")).toBe("TB");
    // The empty assistant_id sentinel keeps the canvas from fetching live
    // assistant metadata for draft nodes.
    expect(graph.getAttribute("data-all-draft")).toBe("true");
  });

  it("shows the assembling skeleton while streaming before steps arrive", () => {
    render(FlowAIBuilderCanvas, { spec: makeSpec([]), isStreaming: true });

    expect(screen.getByText(m.ai_builder_canvas_assembling())).toBeTruthy();
    expect(screen.queryByTestId("flow-graph")).toBeNull();
  });

  it("shows the empty state when there are no steps and nothing is streaming", () => {
    render(FlowAIBuilderCanvas, { spec: makeSpec([]) });

    expect(screen.getByText(m.flow_graph_empty())).toBeTruthy();
    expect(screen.queryByTestId("flow-graph")).toBeNull();
  });
});
